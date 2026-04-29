import "./globals.css";
import { UploadManagerProvider } from "@/components/upload-provider";

export const metadata = {
  title: "Bloodwork OS",
  description: "Clinical records workspace",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <UploadManagerProvider>{children}</UploadManagerProvider>
      </body>
    </html>
  );
}