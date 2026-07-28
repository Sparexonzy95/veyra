"use client";

import { ApiError, apiFetch, postJson } from "@/lib/api";
import { circleErrorMessage, extractCircleTransactionId } from "@/lib/circle/result";
import type { CircleSdk, CircleSdkModule, CircleSdkResult } from "@/lib/circle/types";
import type { CircleSession, MeResponse } from "@/types/veyra";
import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { SocialLoginProvider } from "@circle-fin/w3s-pw-web-sdk/dist/src/types";
import { toast } from "sonner";

const APP_ID = process.env.NEXT_PUBLIC_CIRCLE_APP_ID ?? "";
const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";
const SESSION_KEY = "veyra.circle.session";
const LOGIN_CONFIG_KEY = "veyra.circle.login-config";
const DEVICE_ID_KEY = "veyra.circle.device-id";

export type WalletActionResult = {
  challengeResult: unknown;
  circleTransactionId: string | null;
};

type ContextValue = {
  sdkReady: boolean;
  busy: boolean;
  status: string | null;
  error: string | null;
  me: MeResponse | null;
  circleSession: CircleSession | null;
  roleDialogOpen: boolean;
  emailDialogOpen: boolean;
  walletSetupOpen: boolean;
  loginWithGoogle: () => Promise<void>;
  requestEmailOtp: (email: string) => Promise<void>;
  verifyEmailOtp: () => void;
  closeEmailDialog: () => void;
  openEmailDialog: () => void;
  chooseClientRole: () => Promise<void>;
  chooseAgentOwnerRole: () => Promise<void>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<MeResponse>;
  executeChallenge: (challengeId: string) => Promise<unknown>;
  executeTrackedChallenge: (challengeId: string, localTransactionId?: string) => Promise<WalletActionResult>;
  circleToken: string | null;
};

const VeyraContext = createContext<ContextValue | null>(null);

function isLoginResult(value: unknown): value is CircleSdkResult {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.userToken === "string" && typeof item.encryptionKey === "string";
}

function readSession(): CircleSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as CircleSession) : null;
  } catch {
    return null;
  }
}

function saveSession(session: CircleSession | null) {
  if (typeof window === "undefined") return;
  if (session) window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  else window.sessionStorage.removeItem(SESSION_KEY);
}

function readLoginConfig(): Record<string, unknown> | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(LOGIN_CONFIG_KEY);
    return raw ? (JSON.parse(raw) as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function saveLoginConfig(config: Record<string, unknown> | null) {
  if (typeof window === "undefined") return;
  if (config) window.sessionStorage.setItem(LOGIN_CONFIG_KEY, JSON.stringify(config));
  else window.sessionStorage.removeItem(LOGIN_CONFIG_KEY);
}

type CircleModalGuard = {
  cleanup: () => void;
  waitForClose: Promise<never>;
};

function makeCircleModalInteractive(): CircleModalGuard {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return {
      cleanup: () => undefined,
      waitForClose: new Promise<never>(() => undefined),
    };
  }

  const body = document.body;
  const previousPointerEvents = body.style.getPropertyValue("pointer-events");
  const previousPointerEventsPriority =
    body.style.getPropertyPriority("pointer-events");

  let cleaned = false;
  let iframeWasPresent = false;
  let rejectClosed: ((reason?: unknown) => void) | null = null;

  const waitForClose = new Promise<never>((_resolve, reject) => {
    rejectClosed = reject;
  });

  const keepInteractive = () => {
    if (cleaned) return;

    // Radix Dialog applies pointer-events: none to <body> while its modal is
    // open. Circle mounts its secure iframe directly under <body>, outside the
    // Radix content, so the iframe can be visible but unable to receive clicks.
    body.style.setProperty("pointer-events", "auto", "important");

    const iframe = document.getElementById("sdkIframe") as
      | HTMLIFrameElement
      | null;

    if (iframe) {
      iframeWasPresent = true;
      iframe.style.setProperty("pointer-events", "auto", "important");
      iframe.removeAttribute("inert");
      return;
    }

    if (iframeWasPresent) {
      rejectClosed?.(
        new Error("Circle confirmation was closed before it completed."),
      );
    }
  };

  const observer = new MutationObserver(keepInteractive);
  observer.observe(body, { childList: true, subtree: true });

  const intervalId = window.setInterval(keepInteractive, 100);
  keepInteractive();

  const cleanup = () => {
    if (cleaned) return;
    cleaned = true;
    observer.disconnect();
    window.clearInterval(intervalId);

    if (previousPointerEvents) {
      body.style.setProperty(
        "pointer-events",
        previousPointerEvents,
        previousPointerEventsPriority,
      );
    } else {
      body.style.removeProperty("pointer-events");
    }
  };

  return { cleanup, waitForClose };
}

export function VeyraProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const sdkRef = useRef<CircleSdk | null>(null);
  const callbackRef = useRef<(result: CircleSdkResult) => Promise<void>>(async () => {});
  const [sdkReady, setSdkReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [circleSession, setCircleSession] = useState<CircleSession | null>(null);
  const [roleDialogOpen, setRoleDialogOpen] = useState(false);
  const [emailDialogOpen, setEmailDialogOpen] = useState(false);
  const [walletSetupOpen, setWalletSetupOpen] = useState(false);

  const refreshMe = useCallback(async () => {
    try {
      const next = await apiFetch<MeResponse>("/api/v1/auth/me/");
      setMe(next);
      return next;
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 401) {
        const unauthenticated: MeResponse = { authenticated: false, onboarding: false };
        setMe(unauthenticated);
        return unauthenticated;
      }
      throw requestError;
    }
  }, []);

  const executeChallenge = useCallback(async (challengeId: string) => {
    const sdk = sdkRef.current;
    const session = circleSession ?? readSession();

    if (!sdk || !session) {
      throw new Error("Reconnect your secure wallet to continue.");
    }

    sdk.setAuthentication({
      userToken: session.userToken,
      encryptionKey: session.encryptionKey,
    });

    const modalGuard = makeCircleModalInteractive();

    try {
      const execution = new Promise<unknown>((resolve, reject) => {
        sdk.execute(challengeId, (sdkError, result) => {
          if (sdkError) {
            reject(new Error(circleErrorMessage(sdkError)));
            return;
          }
          resolve(result);
        });
      });

      return await Promise.race([execution, modalGuard.waitForClose]);
    } finally {
      modalGuard.cleanup();
    }
  }, [circleSession]);

  const executeTrackedChallenge = useCallback(async (
    challengeId: string,
    localTransactionId?: string,
  ): Promise<WalletActionResult> => {
    const challengeResult = await executeChallenge(challengeId);
    const circleTransactionId = extractCircleTransactionId(challengeResult);
    const session = circleSession ?? readSession();
    if (localTransactionId) {
      if (!session) {
        throw new Error("Reconnect your secure wallet to track this transaction.");
      }

      // Circle CREATE_TRANSACTION challenge results contain type/status only.
      // Django already stored Circle's transaction ID from the challenge-create
      // API response. Keep the extracted ID only as a backwards-compatible
      // fallback for SDK versions that include it.
      await postJson(
        `/api/v1/client/transactions/${localTransactionId}/`,
        circleTransactionId
          ? { circle_transaction_id: circleTransactionId }
          : { challenge_completed: true },
        session.userToken,
      );
    }
    return { challengeResult, circleTransactionId };
  }, [circleSession, executeChallenge]);

  const prepareWallet = useCallback(async (
    session: CircleSession,
    redirectPath = "/workspace",
    mode: "CLIENT" | "IDENTITY" = "CLIENT",
  ) => {
    setWalletSetupOpen(true);
    setStatus(
      mode === "CLIENT"
        ? "Setting up your client escrow wallet…"
        : "Finishing secure account sign-in…",
    );
    const body = {
      circle_user_id: session.circleUserId ?? "",
      auth_method: session.authMethod,
      email: session.email ?? "",
      display_name: session.displayName ?? "",
    };
    const init = await postJson<{
      wallet_exists: boolean;
      requires_sync?: boolean;
      challenge_id?: string;
    }>("/api/v1/client/wallet/initialize/", body, session.userToken);

    if (init.challenge_id) {
      setStatus("Confirm wallet setup in the Circle window.");
      await executeChallenge(init.challenge_id);
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
    }

    setStatus("Finishing wallet setup…");
    let lastError: unknown = null;
    for (let attempt = 0; attempt < 10; attempt += 1) {
      try {
        await postJson("/api/v1/client/wallet/sync/", body, session.userToken);
        const nextMe = await refreshMe();
        setWalletSetupOpen(false);
        setStatus(null);
        setRoleDialogOpen(false);
        if (nextMe.authenticated) {
          toast.success(
            mode === "CLIENT"
              ? "Your client wallet is ready."
              : "Secure sign-in is ready. Each agent will receive a separate wallet.",
          );
          router.replace(redirectPath);
          return;
        }
      } catch (syncError) {
        lastError = syncError;
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
      }
    }
    throw lastError ?? new Error("Circle wallet is not available yet.");
  }, [executeChallenge, refreshMe, router]);

  const processLogin = useCallback(async (result: CircleSdkResult) => {
    const previousConfig = readLoginConfig();
    const authMethod = previousConfig?.loginMethod === "EMAIL" ? "EMAIL" : "GOOGLE";
    const email = typeof previousConfig?.email === "string" ? previousConfig.email : "";
    const session: CircleSession = {
      authMethod,
      email,
      encryptionKey: result.encryptionKey,
      refreshToken: result.refreshToken,
      userToken: result.userToken,
      circleUserId: result.userId ?? result.userID ?? "",
    };
    saveSession(session);
    setCircleSession(session);
    setBusy(true);
    setError(null);
    setStatus("Signing you in…");
    try {
      const exchange = await postJson<{
        authenticated: boolean;
        requires_wallet_setup: boolean;
      }>("/api/v1/auth/circle/exchange/", {
        user_token: session.userToken,
        circle_user_id: session.circleUserId ?? "",
        auth_method: session.authMethod,
        email: session.email ?? "",
        display_name: session.displayName ?? "",
      });
      saveLoginConfig(null);
      if (typeof window !== "undefined" && window.location.hash) {
        window.history.replaceState({}, document.title, window.location.pathname + window.location.search);
      }
      if (exchange.authenticated) {
        const nextMe = await refreshMe();
        if (nextMe.capabilities?.some((capability) =>
          capability === "CLIENT" || capability === "AGENT_OWNER"
        )) {
          router.replace("/workspace");
        } else {
          setRoleDialogOpen(true);
        }
      } else if (exchange.requires_wallet_setup) {
        setRoleDialogOpen(true);
      }
      setStatus(null);
      setEmailDialogOpen(false);
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }, [refreshMe, router]);

  callbackRef.current = processLogin;

  useEffect(() => {
    let cancelled = false;
    async function initialise() {
      if (!APP_ID) {
        setError("NEXT_PUBLIC_CIRCLE_APP_ID is missing.");
        setSdkReady(true);
        return;
      }
      try {
        const module = (await import("@circle-fin/w3s-pw-web-sdk")) as unknown as CircleSdkModule;
        if (!module.W3SSdk) throw new Error("Circle Web SDK is unavailable.");
        const storedConfig = readLoginConfig();
        const config: Record<string, unknown> = { appSettings: { appId: APP_ID } };
        if (storedConfig?.loginConfigs) config.loginConfigs = storedConfig.loginConfigs;
        const sdk = new module.W3SSdk(config, (sdkError, result) => {
          if (sdkError) {
            setBusy(false);
            setStatus(null);
            setError(circleErrorMessage(sdkError));
            return;
          }
          if (!isLoginResult(result)) {
            setBusy(false);
            setError("Circle did not return a valid login session.");
            return;
          }
          void callbackRef.current(result);
        });
        if (!cancelled) {
          sdkRef.current = sdk;
          setSdkReady(true);
          const storedSession = readSession();
          if (storedSession) setCircleSession(storedSession);
          try { await refreshMe(); } catch { /* login page will handle it */ }
        }
      } catch (sdkError) {
        if (!cancelled) {
          setSdkReady(true);
          setError(sdkError instanceof Error ? sdkError.message : "Circle SDK failed to load.");
        }
      }
    }
    void initialise();
    return () => { cancelled = true; };
  }, [refreshMe]);

  const loginWithGoogle = useCallback(async () => {
    if (!GOOGLE_CLIENT_ID) {
      setError("NEXT_PUBLIC_GOOGLE_CLIENT_ID is missing.");
      return;
    }
    const sdk = sdkRef.current;
    if (!sdk) {
      setError("Circle Web SDK is still loading.");
      return;
    }
    setBusy(true);
    setError(null);
    setStatus("Preparing Google sign-in…");
    try {
      let deviceId = window.localStorage.getItem(DEVICE_ID_KEY);
      if (!deviceId) {
        deviceId = await sdk.getDeviceId();
        window.localStorage.setItem(DEVICE_ID_KEY, deviceId);
      }
      const device = await postJson<{ deviceToken: string; deviceEncryptionKey: string }>(
        "/api/v1/auth/circle/social/device/",
        { device_id: deviceId },
      );
      const loginConfigs = {
        deviceToken: device.deviceToken,
        deviceEncryptionKey: device.deviceEncryptionKey,
        google: {
          clientId: GOOGLE_CLIENT_ID,
          redirectUri: window.location.origin,
          selectAccountPrompt: true,
        },
      };
      saveLoginConfig({ loginMethod: "GOOGLE", loginConfigs });
      sdk.updateConfigs({ appSettings: { appId: APP_ID }, loginConfigs });
      setStatus("Redirecting to Google…");
      await sdk.performLogin(SocialLoginProvider.GOOGLE);
    } catch (loginError) {
      setBusy(false);
      setStatus(null);
      setError(loginError instanceof Error ? loginError.message : "Google sign-in failed.");
    }
  }, []);

  const requestEmailOtp = useCallback(async (email: string) => {
    const sdk = sdkRef.current;
    if (!sdk) throw new Error("Circle Web SDK is still loading.");
    setBusy(true);
    setError(null);
    setStatus("Requesting your email code…");
    try {
      let deviceId = window.localStorage.getItem(DEVICE_ID_KEY);
      if (!deviceId) {
        deviceId = await sdk.getDeviceId();
        window.localStorage.setItem(DEVICE_ID_KEY, deviceId);
      }
      const payload = await postJson<{
        deviceToken: string;
        deviceEncryptionKey: string;
        otpToken: string;
      }>("/api/v1/auth/circle/email/request/", { device_id: deviceId, email });
      const loginConfigs = {
        deviceToken: payload.deviceToken,
        deviceEncryptionKey: payload.deviceEncryptionKey,
        otpToken: payload.otpToken,
        email: { email },
      };
      saveLoginConfig({ loginMethod: "EMAIL", email, loginConfigs });
      sdk.updateConfigs({ appSettings: { appId: APP_ID }, loginConfigs });
      setStatus("Code sent. Continue to Circle verification.");
    } finally {
      setBusy(false);
    }
  }, []);

  const verifyEmailOtp = useCallback(() => {
    if (!sdkRef.current) return;
    setBusy(true);
    setStatus("Opening email verification…");
    sdkRef.current.verifyOtp();
  }, []);

  const chooseClientRole = useCallback(async () => {
    const session = circleSession ?? readSession();
    if (!session) throw new Error("Complete Circle sign-in first.");
    setBusy(true);
    setError(null);
    try {
      await postJson("/api/v1/onboarding/client/", {
        organisation_name: "",
        notification_email: session.email ?? "",
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
        github_username: "",
      });
      await prepareWallet(session, "/client", "CLIENT");
    } catch (roleError) {
      setWalletSetupOpen(false);
      setError(roleError instanceof Error ? roleError.message : "Wallet setup failed.");
      setBusy(false);
      throw roleError;
    } finally {
      setBusy(false);
    }
  }, [circleSession, prepareWallet]);

  const chooseAgentOwnerRole = useCallback(async () => {
    const session = circleSession ?? readSession();
    if (!session) throw new Error("Complete Circle sign-in first.");
    setBusy(true);
    setError(null);
    try {
      const onboarding = await postJson<{
        wallet_setup_required: boolean;
        wallet_setup_reason?: string;
        agent_wallet_policy: string;
      }>("/api/v1/onboarding/agent-owner/", {
        notification_email: session.email ?? "",
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      });

      if (onboarding.wallet_setup_required) {
        await prepareWallet(session, "/agent-owner", "IDENTITY");
      } else {
        await refreshMe();
        setWalletSetupOpen(false);
        setRoleDialogOpen(false);
        setStatus(null);
        toast.success("Agent workspace ready. Create an agent to provision its dedicated wallet.");
        router.replace("/agent-owner");
      }
    } catch (roleError) {
      setWalletSetupOpen(false);
      setError(roleError instanceof Error ? roleError.message : "Agent owner setup failed.");
      setBusy(false);
      throw roleError;
    } finally {
      setBusy(false);
    }
  }, [circleSession, prepareWallet, refreshMe, router]);

  const logout = useCallback(async () => {
    try { await postJson("/api/v1/auth/logout/", {}); } catch { /* clear locally anyway */ }
    saveSession(null);
    saveLoginConfig(null);
    setCircleSession(null);
    setMe(null);
    setRoleDialogOpen(false);
    router.replace("/login");
  }, [router]);

  const value = useMemo<ContextValue>(() => ({
    sdkReady,
    busy,
    status,
    error,
    me,
    circleSession,
    roleDialogOpen,
    emailDialogOpen,
    walletSetupOpen,
    loginWithGoogle,
    requestEmailOtp,
    verifyEmailOtp,
    closeEmailDialog: () => setEmailDialogOpen(false),
    openEmailDialog: () => setEmailDialogOpen(true),
    chooseClientRole,
    chooseAgentOwnerRole,
    logout,
    refreshMe,
    executeChallenge,
    executeTrackedChallenge,
    circleToken: circleSession?.userToken ?? null,
  }), [
    sdkReady, busy, status, error, me, circleSession, roleDialogOpen, emailDialogOpen,
    walletSetupOpen, loginWithGoogle, requestEmailOtp, verifyEmailOtp, chooseClientRole,
    chooseAgentOwnerRole, logout, refreshMe, executeChallenge, executeTrackedChallenge,
  ]);

  return <VeyraContext.Provider value={value}>{children}</VeyraContext.Provider>;
}

export function useVeyra() {
  const context = useContext(VeyraContext);
  if (!context) throw new Error("useVeyra must be used within VeyraProvider.");
  return context;
}
