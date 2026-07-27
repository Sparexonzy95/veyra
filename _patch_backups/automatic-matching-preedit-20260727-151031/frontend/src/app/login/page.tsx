"use client";

import { AuthLayout } from "@/components/auth/auth-layout";
import { useVeyra } from "@/components/providers/veyra-provider";
import { Button } from "@/components/ui/button";
import { AlertCircle, Loader2, Mail } from "lucide-react";
import { FcGoogle } from "react-icons/fc";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const {
    sdkReady,
    busy,
    status,
    error,
    me,
    loginWithGoogle,
    openEmailDialog,
  } = useVeyra();
  const router = useRouter();

  useEffect(() => {
    if (me?.authenticated && me.capabilities?.includes("CLIENT")) {
      router.replace("/dashboard");
    }
  }, [me, router]);

  return (
    <div className="flex min-h-svh flex-col items-center justify-center p-6 md:p-10">
      <div className="w-full max-w-sm md:max-w-xl">
        <AuthLayout title="Welcome back!" description="Sign in to Veyra">
          <div className="grid gap-4">
            <Button
              variant="outline"
              type="button"
              onClick={() => void loginWithGoogle()}
              disabled={!sdkReady || busy}
              className="flex w-full items-center justify-center gap-2"
            >
              {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <FcGoogle className="h-5 w-5" />}
              <span>Continue with Google</span>
            </Button>
            <Button
              variant="outline"
              type="button"
              onClick={openEmailDialog}
              disabled={!sdkReady || busy}
              className="flex w-full items-center justify-center gap-2"
            >
              <Mail className="h-5 w-5" />
              <span>Continue with Email</span>
            </Button>
            {status ? (
              <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                {status}
              </div>
            ) : null}
            {error ? (
              <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{error}</span>
              </div>
            ) : null}
            <p className="text-center text-xs text-muted-foreground">
              Circle prepares your secure Arc wallet. No seed phrase or browser wallet is required.
            </p>
          </div>
        </AuthLayout>
      </div>
    </div>
  );
}
