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
  const choice = process.env.MACSO_STATE_RETENTION || '永久';
  const normalized = ({'永久':'permanent','7天':'7','30天':'30','90天':'90'})[choice] || choice;
  const permanentMode = normalized === 'permanent';
  const days = Number(normalized);
  if (!permanentMode && ![7,30,90].includes(days)) throw new Error('Invalid backup retention');
  const draftTag = process.env.MACSO_STATE_RELEASE_TAG || 'macso-desktop-state';
  async function draftRelease(create = false) {
    const found = await github.paginate(github.rest.repos.listReleases, {...context.repo, per_page: 100});
    const matches = found.filter(r => r.tag_name === draftTag);
    if (matches.some(r => !r.draft) || matches.length > 1) throw new Error('Backup release must be a single unpublished draft');
    if (matches.length) return matches[0];
    if (!create) return null;
    const result = await github.rest.repos.createRelease({...context.repo, tag_name: draftTag,
      target_commitish: 'main', name: 'Encrypted desktop files — private draft',
      body: 'Encrypted project desktop state. Keep this release unpublished. Latest and previous checkpoints are retained without automatic expiry. No Google login credentials or macOS privacy permissions.',
      draft: true, generate_release_notes: false, make_latest: 'false'});
    if (!result.data.draft) throw new Error('Private draft creation failed');
    return result.data;
  }
  async function permanentAssets(release) {
    const assets = await github.paginate(github.rest.repos.listReleaseAssets, {...context.repo, release_id: release.id, per_page:100});
    return assets.filter(a => /^state-\d+-\d+\.enc$/.test(a.name) && a.state === 'uploaded').sort((a,b) => b.id-a.id);
  }
  async function downloadPermanent(asset) {
    if (asset.size > 22 * 1024 * 1024) throw new Error('Backup size limit exceeded');
    const result = await github.rest.repos.getReleaseAsset({...context.repo, asset_id:asset.id,
      headers:{accept:'application/octet-stream'}});
    const bytes = Buffer.from(result.data);
    if (bytes.length !== asset.size) throw new Error('Backup download size mismatch');
    if (asset.digest) {
      const digest = 'sha256:' + require('node:crypto').createHash('sha256').update(bytes).digest('hex');
      if (digest !== asset.digest) throw new Error('Backup download digest mismatch');
    }
    await fs.writeFile(encrypted, bytes, {mode:0o600});
  }
  async function savePermanent() {
    const release = await draftRelease(true);
    const data = await fs.readFile(encrypted);
    const name = `${'state-'}${context.runId}-${Date.now()}.enc`;
    const response = await github.rest.repos.uploadReleaseAsset({...context.repo, release_id:release.id, name,
      data, headers:{'content-type':'application/octet-stream','content-length':String(data.length)}});
    const asset = response.data;
    if (asset.state !== 'uploaded' || asset.size !== data.length) throw new Error('Permanent backup upload not verified');
    // Confirm retrieval and the server's digest before replacing any older checkpoint.
    await downloadPermanent(asset);
    const checkpoints = await permanentAssets(release);
    for (const old of checkpoints.slice(2)) {
      try { await github.rest.repos.deleteReleaseAsset({...context.repo, asset_id:old.id}); }
      catch { core.warning('An older encrypted checkpoint could not be pruned.'); }
    }
    return asset.id;
  }
  if (mode === 'restore') {
    const runs = sourceRun ? {data:{workflow_runs:[(await github.rest.actions.getWorkflowRun({...context.repo, run_id:sourceRun})).data]}}
      : await github.rest.actions.listWorkflowRuns({...context.repo,
        workflow_id:'macos-web-desktop.yml', branch:'main', event:'workflow_dispatch', per_page:30});
    let selected = null;
    for (const run of runs.data.workflow_runs) {
      if ((!sourceRun && String(run.id) === String(context.runId)) || run.actor.login !== context.repo.owner) continue;
      const result = await github.rest.actions.listWorkflowRunArtifacts({...context.repo, run_id:run.id, per_page:100});
      const candidates = result.data.artifacts.filter(a => !a.expired && a.name.startsWith(prefix)).sort((a,b) => b.id-a.id);
      if (candidates.length) {selected={run,artifact:candidates[0]}; break;}
    }
    const release = await draftRelease(false);
    const assets = release ? await permanentAssets(release) : [];
    const asset = assets[0];
    if (asset && (!selected || Date.parse(asset.created_at) >= Date.parse(selected.artifact.created_at))) {
      await downloadPermanent(asset);
      await operation('restore', encrypted);
      await status('restored');
      await core.summary.addRaw('Permanent encrypted files restored and authenticated from draft asset '+asset.id+'. Google login and macOS privacy permissions are excluded.\n').write();
      return;
    }
    if (selected) {
      await client.downloadArtifact(selected.artifact.id, {path:folder, findBy:{token:process.env.GH_TOKEN,
        workflowRunId:selected.run.id, repositoryOwner:context.repo.owner, repositoryName:context.repo.repo}});
      await operation('restore', encrypted);
      await status('restored');
      await core.summary.addRaw('Files/preferences restored and authenticated from run '+selected.run.id+'. Google login and macOS privacy permissions are excluded.\n').write();
      return;
    }
    await status('new');
    await core.summary.addRaw('No previous file backup yet. First save will establish one.\n').write();
    return;
  }
  async function save() {
    await status('saving');
    await operation('pack', encrypted);
    if (permanentMode) {
      const id = await savePermanent();
      await status('saved');
      await core.summary.addRaw('Encrypted file checkpoint saved permanently (no automatic expiry) in private draft asset '+id+'. Latest and previous versions retained.\n').write();
      return;
    }
    const name = `${prefix}${context.runId}-${Date.now()}`;
    const uploaded = await client.uploadArtifact(name, [encrypted], folder, {retentionDays: days, compressionLevel: 0});
    if (!uploaded.id || !uploaded.size) throw new Error('Backup upload was not verified');
    await status('saved');
    // Keep the two latest checkpoints of THIS run. Delete only after a new upload succeeds.
    const current = await client.listArtifacts();
    const backups = current.artifacts.filter(a => a.name.startsWith(`${prefix}${context.runId}-`)).sort((a,b) => b.id-a.id);
    for (const old of backups.slice(2)) {
      try { await client.deleteArtifact(old.name); }
      catch { core.warning('A previous encrypted checkpoint could not be pruned.'); }
    }
    await core.summary.addRaw(`Encrypted file checkpoint saved at ${new Date().toISOString()} (artifact ${uploaded.id}, ${days}-day retention).\n`).write();
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
