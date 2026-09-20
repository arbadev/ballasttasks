"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";
import type { TaskPageRequest } from "../services/query";
import { useClock, useDirectoryService, useStepGenerationService, useTaskService } from "@/app/providers";
import { DEFAULT_QUERY, selectTasks, type DueFilter, type PriorityFilter, type ProjectFilter, type Scope, type SignalId, type SortBy, type StatusFilter } from "../model/filter";
import type { Attachment, Person, Project, Task, TaskStatus } from "../model/types";
import type { NewTask, TaskPatch, ProjectEdit } from "../services/types";
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
  setPage(offset: number): void;
  reloadDetail(): void;
  /** Puts a project the directory just created into the sidebar and shows it with the filters and search reset; sort and view are kept. */
  addProject(project: Project): void;
  updateProject(id: string, input: ProjectEdit): Promise<void>;
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
  renameStep(id: string, stepId: string, text: string): Promise<Task>;
  reorderSteps(id: string, stepIds: string[]): Promise<Task>;
  /** Canonical read only, including after a stale step permutation was refused. */
  toggleStep(id: string, stepId: string): Promise<Task>;
  removeStep(id: string, stepId: string): Promise<Task>;
  addComment(id: string, text: string): Promise<Task>;
  addAttachment(id: string, attachment: Attachment, file?: File): Promise<Task>;
  uploadAttachment?(id: string, file: File): Promise<Task>;
  downloadAttachment?(id: string, attachmentId: string): Promise<Blob>;
  removeAttachment?(id: string, attachmentId: string): Promise<Task>;
  /** Also discards the step generation in flight for the task, as the design does. */
  remove(id: string): Promise<void>;
  /** Drops a task the server no longer has, with its generation. Deletes nothing. */
  forget(id: string): Promise<void>;
  /** Read-only recovery of an acknowledged write; forgets a task deleted meanwhile. */
  refresh(id: string): Promise<Task | null>;
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

/** What a failure that carried no message of its own is reported as: it says nothing a view does not already say. */
export const LOAD_FAILED_WITHOUT_DETAIL = "Could not load the tasks.";

/**
 * The directory as the server listed it, except for the projects this client changed after the
 * listing was asked for: those keep their local row, in the order the server gives, with a project
 * created here and not yet listed kept at the end.
 */
function mergeProjects(current: Project[], listed: Project[], revision: number, changedAt: Map<string, number>): Project[] {
  const newer = (id: string) => (changedAt.get(id) ?? 0) > revision;
  const local = new Map(current.map((project) => [project.id, project]));
  const listedIds = new Set(listed.map((project) => project.id));
  return [
    ...listed.map((project) => (newer(project.id) ? local.get(project.id) ?? project : project)),
    ...current.filter((project) => !listedIds.has(project.id) && newer(project.id)),
  ];
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const taskService = useTaskService();
  const directoryService = useDirectoryService();
  const stepGeneration = useStepGenerationService();
  const clock = useClock();
  const [state, dispatch] = useReducer(workspaceReducer, initialWorkspaceState);
  const [directory, setDirectory] = useState<Directory>(EMPTY_DIRECTORY);
  const [now, setNow] = useState(() => clock());
  const [attempt, setAttempt] = useState(0);
  const [detailAttempt, setDetailAttempt] = useState(0);
  const directoryRevision = useRef(0);
  const projectEditSequence = useRef(0);
  const savedProjectEdits = useRef(new Map<string, number>());
  const projectChangedAt = useRef(new Map<string, number>());
  const directorySession = useRef(0);
  useEffect(() => {
    directorySession.current += 1;
    return () => { directorySession.current += 1; };
  }, [directoryService]);
  const selected = state.tasks.find((task) => task.id === state.selectedId);

  useEffect(() => {
    let cancelled = false;
    const revision = directoryRevision.current;
    Promise.all([taskService.query ? Promise.resolve(null) : taskService.list(), directoryService.people(), directoryService.projects(), directoryService.currentUser()])
      .then(([tasks, people, projects, currentUser]) => {
        if (cancelled) return;
        setDirectory((current) => ({ people, projects: mergeProjects(current.projects, projects, revision, projectChangedAt.current), currentUser }));
        if (tasks) dispatch({ type: "tasksLoaded", tasks });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        dispatch({ type: "loadFailed", message: error instanceof Error ? error.message : LOAD_FAILED_WITHOUT_DETAIL });
      });
    return () => {
      cancelled = true;
    };
  }, [taskService, directoryService, attempt]);

  useEffect(() => {
    if (!taskService.query || !directory.currentUser) return;
    let cancelled = false;
    const request: TaskPageRequest = { query: state.query, sort: state.sort, board: state.view === "board", offset: state.pageOffset ?? 0 };
    const revision = state.revision ?? 0;
    // Debounce search typing; ordinary filter/page changes are immediate.
    const timer = setTimeout(() => {
      dispatch({ type: "loadStarted" });
      taskService.query!(request).then((page) => {
        if (cancelled) return;
        if (page.total > 0 && page.offset >= page.total) {
          dispatch({ type: "pageChanged", offset: Math.floor((page.total - 1) / page.limit) * page.limit });
        } else if (page.total === 0 && page.offset > 0) {
          dispatch({ type: "pageChanged", offset: 0 });
        } else dispatch({ type: "queryLoaded", page, request, revision });
      }).catch((error: unknown) => {
        if (!cancelled) dispatch({ type: "loadFailed", message: error instanceof Error ? error.message : "Could not load tasks." });
      });
    }, state.query.search ? 250 : 0);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [taskService, directory.currentUser, state.query, state.sort, state.view, state.pageOffset, state.revision, attempt, now]);

  useEffect(() => {
    stepGeneration.select?.(state.selectedId);
  }, [stepGeneration, state.selectedId]);

  useEffect(() => {
    const visibility = () => stepGeneration.setVisible?.(!document.hidden);
    visibility();
    document.addEventListener("visibilitychange", visibility);
    return () => { document.removeEventListener("visibilitychange", visibility); stepGeneration.setVisible?.(false); };
  }, [stepGeneration]);

  useEffect(() => {
    if (!selected || (selected.detailLoaded !== false && !selected.detailStale)) return;
    let cancelled = false;
    dispatch({ type: "detailStarted" });
    taskService.get(selected.id).then((task) => {
      if (cancelled) return;
      if (task) dispatch({ type: "detailLoaded", task, expected: selected });
      else { dispatch({ type: "taskRemoved", id: selected.id }); stepGeneration.forget?.(selected.id); }
    }).catch((error: unknown) => {
      if (!cancelled) dispatch({ type: "detailFailed", id: selected.id, message: error instanceof Error ? error.message : "Could not load task details." });
    });
    return () => { cancelled = true; };
  }, [selected, taskService, stepGeneration, detailAttempt]);

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
      setPage: (offset) => dispatch({ type: "pageChanged", offset }),
      reloadDetail: () => setDetailAttempt((value) => value + 1),
      reload: () => {
        dispatch({ type: "loadStarted" });
        setAttempt((n) => n + 1);
      },
      updateProject: async (id, input) => {
        const session = directorySession.current;
        const sequence = ++projectEditSequence.current;
        const project = await directoryService.updateProject(id, input);
        if (directorySession.current !== session || (savedProjectEdits.current.get(id) ?? 0) > sequence) return;
        savedProjectEdits.current.set(id, sequence);
        directoryRevision.current += 1;
        projectChangedAt.current.set(id, directoryRevision.current);
        setDirectory((current) => ({ ...current, projects: current.projects.map((item) => item.id === id ? project : item) }));
      },
      addProject: (project) => {
        directoryRevision.current += 1;
        projectChangedAt.current.set(project.id, directoryRevision.current);
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
    [directoryService],
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
    () => state.page ? state.page.ids.flatMap((id) => state.tasks.find((task) => task.id === id) ?? []) : selectTasks(state.tasks, state.query, state.sort, { now, currentUserId, applyStatus }),
    [state.tasks, state.page, state.query, state.sort, now, currentUserId, applyStatus],
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

  const forget = useCallback(
    async (id: string) => {
      dispatch({ type: "taskRemoved", id });
      if (stepGeneration.forget) stepGeneration.forget(id);
      else if (stepGeneration.current()?.taskId === id) await stepGeneration.discard();
    },
    [dispatch, stepGeneration],
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
      renameStep: async (id, stepId, text) => saved(await service.renameStep(id, stepId, text)),
      reorderSteps: async (id, stepIds) => saved(await service.reorderSteps(id, stepIds)),
      toggleStep: async (id, stepId) => saved(await service.toggleStep(id, stepId)),
      removeStep: async (id, stepId) => saved(await service.removeStep(id, stepId)),
      addComment: async (id, text) => saved(await service.addComment(id, text)),
      addAttachment: async (id, attachment, file) => saved(await service.addAttachment(id, attachment, file)),
      uploadAttachment: service.uploadAttachment ? async (id, file) => saved(await service.uploadAttachment!(id, file)) : undefined,
      downloadAttachment: service.downloadAttachment ? (id, attachmentId) => service.downloadAttachment!(id, attachmentId) : undefined,
      removeAttachment: service.removeAttachment ? async (id, attachmentId) => saved(await service.removeAttachment!(id, attachmentId)) : undefined,
      remove: async (id) => {
        await service.remove(id);
        await forget(id);
      },
      forget,
      refresh: async (id) => {
        const task = await (service.refresh ? service.refresh(id) : service.get(id));
        if (task) return saved(task);
        await forget(id);
        return null;
      },
      sync: (task) => {
        saved(task);
      },
    }),
    [service, saved, forget, dispatch, project],
  );
}
