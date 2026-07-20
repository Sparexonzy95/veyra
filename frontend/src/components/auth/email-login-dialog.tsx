"use client";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useVeyra } from "@/components/providers/veyra-provider";
import { useState } from "react";

export function EmailLoginDialog() {
  const {
    emailDialogOpen,
    closeEmailDialog,
    requestEmailOtp,
    verifyEmailOtp,
    busy,
    status,
  } = useVeyra();
  const [email, setEmail] = useState("");
  const [requested, setRequested] = useState(false);

  async function requestCode() {
    await requestEmailOtp(email);
    setRequested(true);
  }

  return (
    <Dialog open={emailDialogOpen} onOpenChange={(open) => !open && closeEmailDialog()}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>Continue with Email</DialogTitle>
          <DialogDescription>
            Enter your email and complete the Circle verification window.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-2">
          <div className="grid gap-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              disabled={requested || busy}
            />
          </div>
          {status ? <p className="text-sm text-muted-foreground">{status}</p> : null}
          {!requested ? (
            <Button onClick={requestCode} disabled={!email || busy}>
              Send verification code
            </Button>
          ) : (
            <Button onClick={verifyEmailOtp} disabled={busy}>
              Open Circle verification
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
