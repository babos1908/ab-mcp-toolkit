/**
 * Hints added to a failed tool response when the script output carries a
 * known AB failure signature that the script itself may not have explained.
 */

/**
 * AB 2.9 opens a project whose Project Information is marked Released in
 * READ-ONLY mode, and every save() then fails with
 *   "This project has been opened in read-only mode and cannot be saved ..."
 * (live 2026-10-17). Scripts that go through save_project_checked() already
 * say so; this catches every other mutator centrally.
 */
export function readOnlyHint(output: string): string | null {
  if (!/opened in read-only mode|ERR_PROJECT_READ_ONLY/i.test(output)) return null;
  return (
    'HINT: the project is open READ-ONLY -- AB does this for a project/library whose Project ' +
    'Information is marked Released, and nothing can be saved. To modify it, call ' +
    'set_project_info(released=false) (bump the version too), then retry.'
  );
}
