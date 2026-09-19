"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useState, type ReactNode } from "react";
import { useClock, useDirectoryService, useStepGenerationService, useTaskService } from "@/app/providers";
import { DEFAULT_QUERY, selectTasks, type DueFilter, type PriorityFilter, type ProjectFilter, type Scope, type SignalId, type SortBy, type StatusFilter } from "../model/filter";
import type { Attachment, Person, Project, Task, TaskStatus } from "../model/types";
import type { NewTask, TaskPatch } from "../services/types";
import { initialWorkspaceState, workspaceReducer, type View, type WorkspaceAction, type WorkspaceState } from "./reducer";

export interface WorkspaceActions {
  selectScope(scope: Scope): void;
  /** Selecting the active project goes back to all projects. */
  toggleProject(project: ProjectFilter): void;
  setStatusFilter(status: StatusFilter): void;
  setDueFilter(due: DueFilter): void;
  setPriorityFilter(priority: PriorityFilter): void;
  setSort(sort: SortBy): void;
  setSearch(search: string): void;
  toggleSignal(signal: SignalId): void;
  clearSignal(): void;
  setView(view: View): void;
  selectTask(id: string): void;
  clearSelection(): void;
  /** Fetches the tasks again, after a load error. */
  reload(): void;
  /** Puts a project the directory just created into the sidebar and shows it with the filters and search reset; sort and view are kept. */
  addProject(project: Project): void;
}

export interface Directory {
  people: Person[];
  projects: Project[];
  currentUser: Person | null;
}

/** Task mutations: each calls TaskService, then syncs the saved task into the workspace. */
export interface TaskCommands {
  /** Creates into the selected project (the Inbox when none is); `open` selects the new task. */
  create(input: NewTask, options?: { open?: boolean }): Promise<Task>;
  update(id: string, patch: TaskPatch, note?: string): Promise<Task>;
  move(id: string, status: TaskStatus): Promise<Task>;
  toggleDone(id: string): Promise<Task>;
  addStep(id: string, text: string): Promise<Task>;
  toggleStep(id: string, stepId: string): Promise<Task>;
  removeStep(id: string, stepId: string): Promise<Task>;
  addComment(id: string, text: string): Promise<Task>;
  addAttachment(id: string, attachment: Attachment): Promise<Task>;
  /** Also discards the step generation in flight for the task, as the design does. */
  remove(id: string): Promise<void>;
  /** Puts a task saved elsewhere (accepted generated steps, for one) into the workspace. */
  sync(task: Task): void;
}

interface WorkspaceContextValue {
  state: WorkspaceState;
  dispatch: (action: WorkspaceAction) => void;
  actions: WorkspaceActions;
  directory: Directory;
  now: number;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

const EMPTY_DIRECTORY: Directory = { people: [], projects: [], currentUser: null };

/** How often "now" is sampled from the clock, so due labels roll over without a reload. */
const NOW_REFRESH_MS = 60_000;

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const taskService = useTaskService();
  const directoryService = useDirectoryService();
  const clock = useClock();
  const [state, dispatch] = useReducer(workspaceReducer, initialWorkspaceState);
  const [directory, setDirectory] = useState<Directory>(EMPTY_DIRECTORY);
  const [now, setNow] = useState(() => clock());
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    Promise.all([taskService.list(), directoryService.people(), directoryService.projects(), directoryService.currentUser()])
      .then(([tasks, people, projects, currentUser]) => {
        if (cancelled) return;
        setDirectory({ people, projects, currentUser });
        dispatch({ type: "tasksLoaded", tasks });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        dispatch({ type: "loadFailed", message: error instanceof Error ? error.message : "Could not load the tasks." });
      });
    return () => {
      cancelled = true;
    };
  }, [taskService, directoryService, attempt]);

  useEffect(() => {
    const timer = setInterval(() => setNow(clock()), NOW_REFRESH_MS);
    return () => clearInterval(timer);
  }, [clock]);

  const actions = useMemo<WorkspaceActions>(
    () => ({
      selectScope: (scope) => dispatch({ type: "scopeSelected", scope }),
      toggleProject: (project) => dispatch({ type: "projectToggled", project }),
      setStatusFilter: (status) => dispatch({ type: "statusFilterChanged", status }),
      setDueFilter: (due) => dispatch({ type: "dueFilterChanged", due }),
      setPriorityFilter: (priority) => dispatch({ type: "priorityFilterChanged", priority }),
      setSort: (sort) => dispatch({ type: "sortChanged", sort }),
      setSearch: (search) => dispatch({ type: "searchChanged", search }),
      toggleSignal: (signal) => dispatch({ type: "signalToggled", signal }),
      clearSignal: () => dispatch({ type: "signalCleared" }),
      setView: (view) => dispatch({ type: "viewChanged", view }),
      selectTask: (id) => dispatch({ type: "taskSelected", id }),
      clearSelection: () => dispatch({ type: "selectionCleared" }),
      reload: () => {
        dispatch({ type: "loadStarted" });
        setAttempt((n) => n + 1);
      },
      addProject: (project) => {
        setDirectory((d) => ({ ...d, projects: [...d.projects, project] }));
        // A scope, signal, filter or search left on would hide the project's first, unassigned tasks.
        dispatch({ type: "scopeSelected", scope: "all" });
        dispatch({ type: "signalCleared" });
        dispatch({ type: "statusFilterChanged", status: DEFAULT_QUERY.status });
        dispatch({ type: "dueFilterChanged", due: DEFAULT_QUERY.due });
        dispatch({ type: "priorityFilterChanged", priority: DEFAULT_QUERY.priority });
        dispatch({ type: "searchChanged", search: DEFAULT_QUERY.search });
        dispatch({ type: "projectToggled", project: project.id });
      },
    }),
    [],
  );

  const value = useMemo(() => ({ state, dispatch, actions, directory, now }), [state, actions, directory, now]);
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

function useWorkspaceContext(): WorkspaceContextValue {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("Workspace hooks must be used inside <WorkspaceProvider>.");
  return value;
}

export function useWorkspace(): { state: WorkspaceState; actions: WorkspaceActions } {
  const { state, actions } = useWorkspaceContext();
  return { state, actions };
}

export function useDirectory(): Directory {
  return useWorkspaceContext().directory;
}

/** The current time, sampled from the injected clock. Pass it to the model's functions. */
export function useNow(): number {
  return useWorkspaceContext().now;
}

/** The tasks the current view shows: filtered, then sorted. The board passes `applyStatus: false`. */
export function useVisibleTasks(options: { applyStatus?: boolean } = {}): Task[] {
  const { state, directory, now } = useWorkspaceContext();
  const applyStatus = options.applyStatus ?? true;
  const currentUserId = directory.currentUser?.id ?? "";
  return useMemo(
    () => selectTasks(state.tasks, state.query, state.sort, { now, currentUserId, applyStatus }),
    [state.tasks, state.query, state.sort, now, currentUserId, applyStatus],
  );
}

export function useTaskCommands(): TaskCommands {
  const service = useTaskService();
  const stepGeneration = useStepGenerationService();
  const { state, dispatch } = useWorkspaceContext();
  const project = state.query.project;

  const saved = useCallback(
    (task: Task) => {
      dispatch({ type: "taskSaved", task });
      return task;
    },
    [dispatch],
  );

  return useMemo<TaskCommands>(
    () => ({
      create: async (input, options) => {
        const task = saved(await service.create({ ...input, project: input.project ?? (project === "all" ? "inbox" : project) }));
        if (options?.open) dispatch({ type: "taskSelected", id: task.id });
        return task;
      },
      update: async (id, patch, note) => saved(await service.update(id, patch, note)),
      move: async (id, status) => saved(await service.move(id, status)),
      toggleDone: async (id) => saved(await service.toggleDone(id)),
      addStep: async (id, text) => saved(await service.addStep(id, text)),
      toggleStep: async (id, stepId) => saved(await service.toggleStep(id, stepId)),
      removeStep: async (id, stepId) => saved(await service.removeStep(id, stepId)),
      addComment: async (id, text) => saved(await service.addComment(id, text)),
      addAttachment: async (id, attachment) => saved(await service.addAttachment(id, attachment)),
      remove: async (id) => {
        await service.remove(id);
        dispatch({ type: "taskRemoved", id });
        if (stepGeneration.current()?.taskId === id) await stepGeneration.discard();
      },
      sync: (task) => {
        saved(task);
      },
    }),
    [service, stepGeneration, saved, dispatch, project],
  );
}
