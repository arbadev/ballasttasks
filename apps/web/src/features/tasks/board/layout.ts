/**
 * The board's grid, shared by the board and its loading skeleton so both occupy the same
 * space. Four columns that never shrink below a readable card; below `md` they become fixed
 * 280px columns that scroll sideways inside the board and snap, so the page never does.
 * `relative` matters: it makes the grid the containing block of the visually hidden text in
 * its columns, which would otherwise escape the scroller and widen the page.
 */
export const BOARD_GRID =
  "relative grid flex-1 grid-cols-[repeat(4,minmax(240px,1fr))] items-start gap-5 overflow-x-auto px-8 pt-6 pb-8 max-md:snap-x max-md:snap-mandatory max-md:scroll-px-4 max-md:grid-cols-[repeat(4,280px)] max-md:px-4";
