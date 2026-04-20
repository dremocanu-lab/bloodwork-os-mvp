import "./globals.css";

export const metadata = {
  title: "Bloodwork OS",
  description: "Clinical record workspace",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}