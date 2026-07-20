"use client";

import { ThemeProvider } from "@/components/providers/theme.provider";
import { VeyraProvider } from "@/components/providers/veyra-provider";

export function AppProvider({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider defaultTheme="system">
      <VeyraProvider>{children}</VeyraProvider>
    </ThemeProvider>
  );
}
