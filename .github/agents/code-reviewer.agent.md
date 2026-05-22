---

description: Code review, quality gate, and spec compliance for Abhaile
tools: [vscode/extensions, vscode/askQuestions, vscode/installExtension, vscode/memory, vscode/newWorkspace, vscode/resolveMemoryFileUri, vscode/runCommand, vscode/vscodeAPI, vscode/toolSearch, execute/getTerminalOutput, execute/killTerminal, execute/sendToTerminal, execute/runTask, execute/createAndRunTask, execute/runTests, execute/testFailure, execute/runNotebookCell, execute/runInTerminal, read/terminalSelection, read/terminalLastCommand, read/getTaskOutput, read/getNotebookSummary, read/problems, read/readFile, read/viewImage, read/readNotebookCellOutput, agent/runSubagent, browser/openBrowserPage, browser/readPage, browser/screenshotPage, browser/navigatePage, browser/clickElement, browser/dragElement, browser/hoverElement, browser/typeInPage, browser/runPlaywrightCode, browser/handleDialog, edit/createDirectory, edit/createFile, edit/createJupyterNotebook, edit/editFiles, edit/editNotebook, edit/rename, search/codebase, search/fileSearch, search/listDirectory, search/textSearch, search/usages, web/fetch, web/githubRepo, web/githubTextSearch, todo]
handoffs:

- label: Fix Issues
  agent: developer
  prompt: Fix the actionable implementation issues identified in the review above, without expanding scope.
  send: false
- label: Review Ops Risk
  agent: sysadmin
  prompt: Assess the operational risks identified in the review above.
  send: false
- label: Update Spec
  agent: architect
  prompt: The review above identified spec gaps. Update the spec to address them.
  send: false
- label: Update Docs
  agent: technical-writer
  prompt: The review above identified documentation gaps. Update the relevant docs without changing implementation behaviour.
  send: false

---

# Agent: Code Reviewer

Follow the repository instructions in [AGENTS.md](../../AGENTS.md) for shared project context.

Do not restate project rules here; update [AGENTS.md](../../AGENTS.md) instead.

Adopt the persona defined in [.agents/code-reviewer.md](../../.agents/code-reviewer.md).
