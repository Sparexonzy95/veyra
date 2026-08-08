"use client";

import { CreateJobDialog } from "@/components/jobs/create-job-dialog";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

/**
 * Create Job as a normal dashboard page.
 *
 * The builder used to open as a dialog over an otherwise empty page, which
 * meant a close X, an overlay, and a viewport-height scroll area on a route
 * the user navigated to deliberately. Here it renders inline: `open` is a
 * constant because there is nothing to open or dismiss, and `onOpenChange`
 * only fires when the builder finishes and wants to leave.
 */
export default function CreateJobPage() {
  const router = useRouter();

  return (
    <>
      <Link
        href="/client/jobs"
        className="inline-flex w-fit items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to Jobs
      </Link>

      <CreateJobDialog
        asPage
        open
        onOpenChange={(next) => {
          if (!next) router.push("/client/jobs");
        }}
        onComplete={() => router.push("/client/jobs")}
      />
    </>
  );
}
