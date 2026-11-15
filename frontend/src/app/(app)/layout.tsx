import { Suspense } from "react";
import { Shell } from "@/components/Shell";
import { Loading } from "@/components/ui";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  // The shell reads the current project from the address, which needs a Suspense boundary in a static export.
  return (
    <Suspense fallback={<Loading rows={6} />}>
      <Shell>{children}</Shell>
    </Suspense>
  );
}
