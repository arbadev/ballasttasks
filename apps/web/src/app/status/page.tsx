import Link from "next/link";
import { StatusCard } from "@/features/health/StatusCard";

export default function StatusPage() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-6 p-6">
      <StatusCard />
      <Link href="/" className="text-[13px]">
        Back to tasks
      </Link>
    </main>
  );
}
