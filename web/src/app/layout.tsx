import type { Metadata } from "next";
import { Geist_Mono, IBM_Plex_Sans_Thai, Inter } from "next/font/google";
import { Providers } from "@/components/providers";
import "./globals.css";

// Inter for Latin text (as on framer.com); Thai glyphs fall through to IBM Plex Sans Thai.
const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const thai = IBM_Plex_Sans_Thai({
  variable: "--font-thai",
  subsets: ["thai"],
  weight: ["300", "400", "500", "600", "700"],
});
const mono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Compliance Copilot",
  description: "ผู้ช่วยค้นคว้ากฎระเบียบสำหรับธนาคารและธุรกิจหลักทรัพย์ ตอบพร้อมแหล่งอ้างอิงที่ตรวจสอบได้",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="th"
      suppressHydrationWarning
      className={`${inter.variable} ${thai.variable} ${mono.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
