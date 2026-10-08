const fs = require('node:fs/promises');
const path = require('node:path');
const {promisify} = require('node:util');
const execFile = promisify(require('node:child_process').execFile);

exports.run = async function ({github, context, core, mode, sourceRun}) {
  const {DefaultArtifactClient} = await import('@actions/artifact');
  const client = new DefaultArtifactClient();
  const folder = path.join(process.env.RUNNER_TEMP, 'macso-state');
  const encrypted = path.join(folder, 'state.enc');
  const statusPath = path.join(process.env.RUNNER_TEMP, 'macso-state-status.json');
  const requestPath = path.join(process.env.RUNNER_TEMP, 'macso-state-request');
  const python = process.env.MACSO_STATE_PYTHON;
  const source = path.join(process.env.GITHUB_WORKSPACE, 'remote-desktop/state.py');
  await fs.mkdir(folder, {recursive: true, mode: 0o700});
  async function status(state) {
    const data = JSON.stringify({state, at: new Date().toISOString()});
    await fs.writeFile(statusPath + '.new', data, {mode: 0o600});
    await fs.rename(statusPath + '.new', statusPath);
  }
  async function operation(action, file) {
    const args = [source, action, file];
    if (process.env.MACSO_STATE_HOME) args.push('--home', process.env.MACSO_STATE_HOME);
    await execFile(python, args, {timeout: 120000, maxBuffer: 1024 * 1024});
  }
  const prefix = 'macso-state-v1-';
  if (mode === 'restore') {
    const runs = sourceRun ? {data: {workflow_runs: [(await github.rest.actions.getWorkflowRun({...context.repo, run_id: sourceRun})).data]}}
      : await github.rest.actions.listWorkflowRuns({...context.repo,
        workflow_id: 'macos-web-desktop.yml', branch: 'main', event: 'workflow_dispatch', per_page: 30});
    for (const run of runs.data.workflow_runs) {
      if ((!sourceRun && String(run.id) === String(context.runId)) || run.actor.login !== context.repo.owner) continue;
      const result = await github.rest.actions.listWorkflowRunArtifacts({...context.repo, run_id: run.id, per_page: 100});
      const candidates = result.data.artifacts.filter(a => !a.expired && a.name.startsWith(prefix)).sort((a,b) => b.id-a.id);
      if (!candidates.length) continue;
      const options = {path: folder, findBy: {token: process.env.GH_TOKEN,
        workflowRunId: run.id, repositoryOwner: context.repo.owner, repositoryName: context.repo.repo}};
      await client.downloadArtifact(candidates[0].id, options);
      await operation('restore', encrypted);
      await status('restored');
      await core.summary.addRaw(`Files/preferences restored and authenticated from run ${run.id}. Google login and macOS privacy permissions are excluded.\n`).write();
      return;
    }
    await status('new');
    await core.summary.addRaw('No previous file backup yet. First save will establish one.\n').write();
    return;
  }
  async function save() {
    await status('saving');
    await operation('pack', encrypted);
    const name = `${prefix}${context.runId}-${Date.now()}`;
    const uploaded = await client.uploadArtifact(name, [encrypted], folder, {retentionDays: 30, compressionLevel: 0});
    if (!uploaded.id || !uploaded.size) throw new Error('Backup upload was not verified');
    await status('saved');
    // Keep the two latest checkpoints of THIS run. Delete only after a new upload succeeds.
    const current = await client.listArtifacts();
    const backups = current.artifacts.filter(a => a.name.startsWith(`${prefix}${context.runId}-`)).sort((a,b) => b.id-a.id);
    for (const old of backups.slice(2)) {
      try { await client.deleteArtifact(old.name); }
      catch { core.warning('A previous encrypted checkpoint could not be pruned.'); }
    }
    await core.summary.addRaw(`Encrypted file checkpoint saved at ${new Date().toISOString()} (artifact ${uploaded.id}, 30-day retention).\n`).write();
  }
  async function safeSave() {
    try { await save(); return true; }
    catch { await status('failed'); core.warning('File save failed; previous encrypted checkpoint is retained. Check the 20 MiB limit and Actions storage availability.'); return false; }
  }
  if (mode === 'save') {
    if (!await safeSave()) core.setFailed('Encrypted file save did not complete.');
    return;
  }
  const pid = Number((await fs.readFile(path.join(process.env.RUNNER_TEMP, 'web-desktop.pid'), 'utf8')).trim());
  if (!Number.isSafeInteger(pid) || pid <= 0) throw new Error('Invalid desktop process');
  let deadline = 0;
  while (true) {
    let alive = true;
    try { process.kill(pid, 0); } catch { alive = false; }
    let requested = false;
    try { await fs.unlink(requestPath); requested = true; } catch (e) { if (e.code !== 'ENOENT') throw e; }
    if (!alive) break;
    if (requested || Date.now() >= deadline) {
      await safeSave();
      deadline = Date.now() + 20 * 60 * 1000;
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  if (!await safeSave()) core.setFailed('Final encrypted file save did not complete.');
};
