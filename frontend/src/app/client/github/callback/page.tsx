"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { postJson } from "@/lib/api";
import {
  clearCapturedCallbackParams,
  clearStoredInstallState,
  getCapturedCallbackParams,
  readStoredInstallState,
} from "@/lib/github-install";
import { CheckCircle2, Github, Loader2, ShieldAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

const DEFAULT_RETURN = "/client/github";

/**
 * GitHub App installation callback (the app's Setup URL).
 *
 * GitHub sends the browser here after the user finishes the installation
 * screens, with:
 *
 *   - `installation_id` + `setup_action=install` for a new installation
 *   - `installation_id` + `setup_action=update` when repository access changed
 *   - `setup_action=request` and no installation id when an organisation owner
 *     still has to approve the request
 *   - optionally `code`, if the app also asks for user authorisation. That is
 *     an OAuth code and is never used here as an installation id or as state.
 *
 * The parameters are read by `@/lib/github-install` at module-evaluation time,
 * before React mounts, because the surrounding WorkspaceShell can call
 * `router.replace` from an effect while the session resolves and that wipes the
 * query string. This component only ever reads that snapshot; it does not touch
 * the URL, and it does not navigate until it has reached a final state.
 */
export default function GitHubCallbackPage() {
  const router = useRouter();
  const [phase, setPhase] = useState<"working" | "done" | "error">("working");
  const [message, setMessage] = useState("Confirming repository access…");
  const [returnPath, setReturnPath] = useState(DEFAULT_RETURN);
  const [showRetry, setShowRetry] = useState(false);
  // Strict Mode mounts effects twice in development; the exchange must not be
  // attempted twice with the same single-use state.
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    const captured = getCapturedCallbackParams();
    const stored = readStoredInstallState();
    const destination = stored.returnPath || DEFAULT_RETURN;
    setReturnPath(destination);

    // Development diagnostics: presence and shape only. The state, the OAuth
    // code and any token value are deliberately never printed.
    if (process.env.NODE_ENV !== "production") {
      console.info("[veyra] github setup callback", {
        pathname: window.location.pathname,
        installation_id_present: Boolean(captured.installationId),
        installation_id_numeric: /^\d+$/.test(captured.installationId),
        setup_action: captured.setupAction || "(none)",
        state_present: Boolean(captured.state),
        state_recovered_from_session:
          !captured.state && Boolean(stored.state),
        code_present: captured.hasCode,
        query_keys: captured.presentKeys,
      });
    }

    // Nothing arrived at all. This is a redirect/configuration problem, not a
    // finished installation, and it must not be reported as either a success
    // or as GitHub sending a malformed payload.
    if (captured.empty) {
      setPhase("error");
      setShowRetry(true);
      setMessage(
        "This page was opened without any GitHub installation details. That usually means the Veyra GitHub App's Setup URL is not pointing at this page, or the connection was not started from Veyra. Start the connection again, and check the app's Setup URL if it keeps happening.",
      );
      return;
    }

    // Organisation installs can stop at "pending owner approval". There is
    // genuinely no installation to link yet, which is a valid outcome.
    if (captured.setupAction === "request" && !captured.installationId) {
      clearCapturedCallbackParams();
      clearStoredInstallState();
      setPhase("done");
      setMessage(
        "Your installation request was sent to the organisation owners. Veyra will finish connecting once an owner approves it.",
      );
      window.setTimeout(() => router.replace(destination), 1800);
      return;
    }

    if (!captured.installationId) {
      setPhase("error");
      setShowRetry(true);
      setMessage(
        captured.setupAction
          ? `GitHub finished with "${captured.setupAction}" but did not return an installation to link. Start the connection again from Veyra.`
          : "GitHub returned an incomplete installation response.",
      );
      return;
    }

    if (!/^\d+$/.test(captured.installationId)) {
      setPhase("error");
      setShowRetry(true);
      setMessage("GitHub returned an installation identifier Veyra cannot read.");
      return;
    }

    // URL state wins; the stored copy is only a fallback for the case where
    // GitHub sent us here without echoing it. The check itself is never skipped.
    const stateValue = captured.state || stored.state;
    if (!stateValue) {
      setPhase("error");
      setShowRetry(true);
      setMessage(
        "Start the GitHub connection from Veyra so the installation can be linked securely to your account.",
      );
      return;
    }

    void postJson<{
      return_path: string;
      repositories: Array<{ id: string }>;
    }>("/api/v1/client/github/app/install/complete/", {
      installation_id: captured.installationId,
      state: stateValue,
      ...(captured.setupAction ? { setup_action: captured.setupAction } : {}),
    })
      .then((result) => {
        // Only now, with the exchange finished and repositories synchronised,
        // is it safe to discard the captured parameters.
        clearCapturedCallbackParams();
        clearStoredInstallState();
        const target = result.return_path || destination;
        setReturnPath(target);
        const count = result.repositories.length;
        setMessage(
          count === 0
            ? "GitHub connected, but no repositories were approved yet. Choose at least one repository for Veyra in GitHub."
            : `GitHub connected. ${count} ${count === 1 ? "repository is" : "repositories are"} available to Veyra.`,
        );
        setPhase("done");
        window.setTimeout(() => router.replace(target), 1200);
      })
      .catch((error) => {
        // Keep the captured parameters: the failure may be transient and the
        // page can be reloaded to retry the same installation.
        setPhase("error");
        setShowRetry(true);
        setMessage(
          error instanceof Error
            ? error.message
            : "GitHub connection could not be completed.",
        );
      });
  }, [router]);

  return (
    <div className="mx-auto flex min-h-[60vh] max-w-xl items-center justify-center">
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Github className="h-5 w-5" /> Veyra GitHub App
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-5 text-center">
          {phase === "working" ? <Loader2 className="mx-auto h-10 w-10 animate-spin text-primary" /> : null}
          {phase === "done" ? <CheckCircle2 className="mx-auto h-10 w-10 text-emerald-600" /> : null}
          {phase === "error" ? <ShieldAlert className="mx-auto h-10 w-10 text-destructive" /> : null}
          <p className="text-sm text-muted-foreground">{message}</p>
          {phase === "error" ? (
            <div className="flex flex-wrap justify-center gap-2">
              {showRetry ? (
                <Button onClick={() => router.replace("/client/github")}>
                  Retry connection
                </Button>
              ) : null}
              <Button variant="outline" onClick={() => router.replace(returnPath)}>
                Back to Veyra
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
