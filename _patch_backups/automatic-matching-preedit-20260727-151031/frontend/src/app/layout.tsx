import type { Metadata } from "next";
import { AppProvider } from "@/components/providers/app-provider";
import { GlobalAuthDialogs } from "@/components/auth/global-auth-dialogs";
import { Toaster } from "sonner";
import "./globals.css";

export const metadata: Metadata = {
  title: "Veyra",
  description: "Autonomous work. Verified outcomes. USDC settlement.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="antialiased">
        <AppProvider>
          {children}
          <GlobalAuthDialogs />
        </AppProvider>
        <Toaster richColors />
      </body>
    </html>
  );
}
