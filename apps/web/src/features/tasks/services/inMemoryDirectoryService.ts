import type { Person, Project } from "../model/types";
import { CURRENT_USER_ID, SEED_PEOPLE, SEED_PROJECTS } from "./seed";
import type { DirectoryService } from "./types";

export class InMemoryDirectoryService implements DirectoryService {
  async people(): Promise<Person[]> {
    return [...SEED_PEOPLE];
  }

  async projects(): Promise<Project[]> {
    return [...SEED_PROJECTS];
  }

  async currentUser(): Promise<Person> {
    return SEED_PEOPLE.find((p) => p.id === CURRENT_USER_ID)!;
  }
}
