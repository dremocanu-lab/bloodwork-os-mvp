import "./globals.css";
import { UploadManagerProvider } from "@/components/upload-provider";

export const metadata = {
  title: "Bragi Health",
  description: "Clinical records workspace",
};

/**
 * Theme bootstrap.
 *
 * Applies the saved theme before first paint so there is no flash of the
 * wrong theme, and — more importantly — so the theme is applied at all.
 * Previously the only code that added the `dark` class on load lived inside
 * <ThemeToggle>, which happened to be rendered in the sidebar; once
 * preferences moved into the account menu (a popover that only mounts its
 * contents when opened) nothing restored the saved theme on navigation.
 *
 * Runs before hydration, reads the same key the toggle writes, and falls back
 * to the OS preference when the user has not chosen.
 *
 * Rendered as the first child of <body> rather than inside a manual <head>:
 * node_modules/next/dist/docs (layout.md) says a root layout should not
 * hand-roll <head>, and metadata already goes through the Metadata API
 * above. As the first thing in the body it still executes before the rest of
 * the document paints, which is all the no-flash guarantee needs.
 */
const THEME_BOOTSTRAP = `
(function () {
  try {
    var saved = localStorage.getItem("bloodwork-theme");
    var dark = saved === "dark" ||
      (saved !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    if (dark) {
      document.documentElement.classList.add("dark");
    }
  } catch (e) {}
})();
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <script id="bragi-theme" dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
        <UploadManagerProvider>{children}</UploadManagerProvider>
      </body>
    </html>
  );
}
