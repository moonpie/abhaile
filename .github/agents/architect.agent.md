---

description: System design, specs, ADRs, and technical coherence for Abhaile
tools: [vscode/extensions, vscode/askQuestions, vscode/installExtension, vscode/memory, vscode/newWorkspace, vscode/resolveMemoryFileUri, vscode/runCommand, vscode/vscodeAPI, vscode/toolSearch, execute/getTerminalOutput, execute/killTerminal, execute/sendToTerminal, execute/runTask, execute/createAndRunTask, execute/runTests, execute/testFailure, execute/runNotebookCell, execute/runInTerminal, read/terminalSelection, read/terminalLastCommand, read/getTaskOutput, read/getNotebookSummary, read/problems, read/readFile, read/viewImage, read/readNotebookCellOutput, agent/runSubagent, browser/openBrowserPage, browser/readPage, browser/screenshotPage, browser/navigatePage, browser/clickElement, browser/dragElement, browser/hoverElement, browser/typeInPage, browser/runPlaywrightCode, browser/handleDialog, edit/createDirectory, edit/createFile, edit/createJupyterNotebook, edit/editFiles, edit/editNotebook, edit/rename, search/codebase, search/fileSearch, search/listDirectory, search/textSearch, search/usages, web/fetch, web/githubRepo, web/githubTextSearch, todo]
handoffs:

- label: Implement Spec
  agent: developer
  prompt: Implement the design or active spec outlined above, following AGENTS.md governance and existing code patterns.
  send: false
- label: Review Design
  agent: code-reviewer
  prompt: Review the design above for correctness, completeness, testability, scope control, and alignment with project principles.
  send: false
- label: Check Ops Implications
  agent: sysadmin
  prompt: Review the design above for operational soundness, systemd/podman/networking implications, permissions, and apply safety.
  send: false
- label: Document Design
  agent: technical-writer
  prompt: Turn the design above into clear project documentation, preserving architecture intent and linking specs or ADRs where appropriate.
  send: false

---

# Agent: Architect

Follow the repository instructions in [AGENTS.md](../../AGENTS.md) for shared project context.

Do not restate project rules here; update [AGENTS.md](../../AGENTS.md) instead.

Adopt the persona defined in [.agents/architect.md](../../.agents/architect.md).
