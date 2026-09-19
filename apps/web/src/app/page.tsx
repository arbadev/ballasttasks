import { TasksApp } from "@/features/tasks/shell/TasksApp";
import { AuthBoundary } from "@/features/auth/AuthBoundary";

export default function Home() {
  return <AuthBoundary><TasksApp /></AuthBoundary>;
}
