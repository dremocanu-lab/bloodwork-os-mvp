import Sidebar from "@/components/sidebar";
import Topbar from "@/components/topbar";

type ShellUser = {
  full_name: string;
  email: string;
  role: "patient" | "doctor" | "admin";
};

export default function AppShell({
  user,
  title,
  subtitle,
  rightContent,
  children,
}: {
  user: ShellUser;
  title: string;
  subtitle?: string;
  rightContent?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="app-page-bg">
      <Sidebar user={user} />
      <main
        style={{
          marginLeft: 270,
          minHeight: "100vh",
          padding: 28,
        }}
      >
        <div style={{ maxWidth: 1500, margin: "0 auto" }}>
          <Topbar
            title={title}
            subtitle={subtitle}
            user={user}
            rightContent={rightContent}
          />
          {children}
        </div>
      </main>
    </div>
  );
}