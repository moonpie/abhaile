---

description: Systemd, podman, networking, security, and operations for Abhaile
tools: [vscode/extensions, vscode/askQuestions, vscode/installExtension, vscode/memory, vscode/newWorkspace, vscode/resolveMemoryFileUri, vscode/runCommand, vscode/vscodeAPI, vscode/toolSearch, execute/getTerminalOutput, execute/killTerminal, execute/sendToTerminal, execute/runTask, execute/createAndRunTask, execute/runTests, execute/testFailure, execute/runNotebookCell, execute/runInTerminal, read/terminalSelection, read/terminalLastCommand, read/getTaskOutput, read/getNotebookSummary, read/problems, read/readFile, read/viewImage, read/readNotebookCellOutput, agent/runSubagent, browser/openBrowserPage, browser/readPage, browser/screenshotPage, browser/navigatePage, browser/clickElement, browser/dragElement, browser/hoverElement, browser/typeInPage, browser/runPlaywrightCode, browser/handleDialog, edit/createDirectory, edit/createFile, edit/createJupyterNotebook, edit/editFiles, edit/editNotebook, edit/rename, search/codebase, search/fileSearch, search/listDirectory, search/textSearch, search/usages, web/fetch, web/githubRepo, web/githubTextSearch, todo]
handoffs:

- label: Implement Changes
  agent: developer
  prompt: Implement the operational recommendations above through the GitOps config/render/apply flow and existing code patterns.
  send: false
- label: Resolve Design Impact
  agent: architect
  prompt: The operational review above identified cross-service, source-of-truth, or architecture implications. Resolve the design impact before implementation.
  send: false
- label: Document Operations
  agent: technical-writer
  prompt: Document the operational procedures, failure modes, and verification steps discussed above.
  send: false

---

# Agent: SysAdmin

Follow the repository instructions in [AGENTS.md](../../AGENTS.md) for shared project context.

Do not restate project rules here; update [AGENTS.md](../../AGENTS.md) instead.

Adopt the persona defined in [.agents/sysadmin.md](../../.agents/sysadmin.md).
