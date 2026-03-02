import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import AuthGate from "@/components/AuthGate";
import Sidebar from "@/components/Sidebar";
import TopBar from "@/components/TopBar";
import ChatSidebar from "@/components/ChatSidebar";
import CommandPalette from "@/components/CommandPalette";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "FlowrexAlgo",
  description: "Algorithmic trading platform for strategy building, backtesting, and live trading",
  icons: {
    icon: "/logo.png",
    apple: "/logo.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body
        className={`${inter.variable} ${jetbrainsMono.variable} antialiased`}
      >
        <TooltipProvider delayDuration={300}>
          <AuthGate>
            <div className="flex h-screen overflow-hidden">
              <Sidebar />
              <div className="flex flex-1 flex-col overflow-hidden min-w-0">
                <TopBar />
                <main className="flex-1 overflow-y-auto p-3 sm:p-4 md:p-6">
                  {children}
                </main>
              </div>
            </div>
            <ChatSidebar />
            <CommandPalette />
          </AuthGate>
          <Toaster richColors position="bottom-right" />
        </TooltipProvider>
      </body>
    </html>
  );
}
