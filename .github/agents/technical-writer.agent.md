---

description: Documentation, runbooks, and ADR drafts for Abhaile
tools: [vscode/extensions, vscode/askQuestions, vscode/installExtension, vscode/memory, vscode/newWorkspace, vscode/resolveMemoryFileUri, vscode/runCommand, vscode/vscodeAPI, vscode/toolSearch, execute/getTerminalOutput, execute/killTerminal, execute/sendToTerminal, execute/runTask, execute/createAndRunTask, execute/runTests, execute/testFailure, execute/runNotebookCell, execute/runInTerminal, read/terminalSelection, read/terminalLastCommand, read/getTaskOutput, read/getNotebookSummary, read/problems, read/readFile, read/viewImage, read/readNotebookCellOutput, agent/runSubagent, browser/openBrowserPage, browser/readPage, browser/screenshotPage, browser/navigatePage, browser/clickElement, browser/dragElement, browser/hoverElement, browser/typeInPage, browser/runPlaywrightCode, browser/handleDialog, edit/createDirectory, edit/createFile, edit/createJupyterNotebook, edit/editFiles, edit/editNotebook, edit/rename, search/codebase, search/fileSearch, search/listDirectory, search/textSearch, search/usages, web/fetch, web/githubRepo, web/githubTextSearch, todo]
handoffs:

- label: Check Design Meaning
  agent: architect
  prompt: Review the documentation above for architectural accuracy and spec/ADR consistency.
  send: false
- label: Check Ops Accuracy
  agent: sysadmin
  prompt: Review the documentation above for operational accuracy, systemd/podman/networking correctness, and safe apply guidance.
  send: false
- label: Review Docs
  agent: code-reviewer
  prompt: Review the documentation above for accuracy, completeness, scope control, and consistency with the implemented behaviour.
  send: false

---

# Agent: Technical Writer

Follow the repository instructions in [AGENTS.md](../../AGENTS.md) for shared project context.

Do not restate project rules here; update [AGENTS.md](../../AGENTS.md) instead.

Adopt the persona defined in [.agents/technical-writer.md](../../.agents/technical-writer.md).
