import { describe, it, expect } from 'vitest';
import { readOnlyHint } from '../../src/response-hints';

describe('readOnlyHint', () => {
  it('fires on the live AB 2.9 save error of a Released project', () => {
    const out =
      'StandardError: The project could not be saved.\n(Reason: This project has been opened in read-only mode ' +
      'and cannot be saved to this file location. You can use the "Save As" command ...)';
    expect(readOnlyHint(out)).toContain('set_project_info(released=false)');
  });

  it('fires on the script-side error code', () => {
    expect(readOnlyHint('SCRIPT_ERROR_CODE: ERR_PROJECT_READ_ONLY')).not.toBeNull();
  });

  it('stays quiet otherwise', () => {
    expect(readOnlyHint('SCRIPT_ERROR: Task not found')).toBeNull();
  });
});
