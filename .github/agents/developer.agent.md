---

description: Python/Jinja2/YAML implementation and testing for Abhaile
tools: [vscode/extensions, vscode/askQuestions, vscode/installExtension, vscode/memory, vscode/newWorkspace, vscode/resolveMemoryFileUri, vscode/runCommand, vscode/vscodeAPI, vscode/toolSearch, execute/getTerminalOutput, execute/killTerminal, execute/sendToTerminal, execute/runTask, execute/createAndRunTask, execute/runTests, execute/testFailure, execute/runNotebookCell, execute/runInTerminal, read/terminalSelection, read/terminalLastCommand, read/getTaskOutput, read/getNotebookSummary, read/problems, read/readFile, read/viewImage, read/readNotebookCellOutput, agent/runSubagent, browser/openBrowserPage, browser/readPage, browser/screenshotPage, browser/navigatePage, browser/clickElement, browser/dragElement, browser/hoverElement, browser/typeInPage, browser/runPlaywrightCode, browser/handleDialog, edit/createDirectory, edit/createFile, edit/createJupyterNotebook, edit/editFiles, edit/editNotebook, edit/rename, search/codebase, search/fileSearch, search/listDirectory, search/textSearch, search/usages, web/fetch, web/githubRepo, web/githubTextSearch, todo]
handoffs:

- label: Review Code
  agent: code-reviewer
  prompt: Review the implementation above against the spec, project conventions, regression risk, and test coverage.
  send: false
- label: Resolve Design Gap
  agent: architect
  prompt: The implementation above exposed a design, schema, source-of-truth, or scope question. Resolve the design issue before further implementation.
  send: false
- label: Check Ops Impact
  agent: sysadmin
  prompt: Review the implementation above for systemd, podman, networking, permissions, and apply safety.
  send: false
- label: Update Docs
  agent: technical-writer
  prompt: Update project documentation to reflect the implemented behaviour, operator impact, and any spec or ADR references.
  send: false

---

# Agent: Developer

Follow the repository instructions in [AGENTS.md](../../AGENTS.md) for shared project context.

Do not restate project rules here; update [AGENTS.md](../../AGENTS.md) instead.

Adopt the persona defined in [.agents/developer.md](../../.agents/developer.md).
