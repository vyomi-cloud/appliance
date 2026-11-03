/* Artifact Registry container image picker — a real browse of the registry's native API:
 * repository (Docker format) -> image -> digest/tag, producing LOCATION-docker.pkg.dev/PROJECT/REPO/IMAGE[:TAG|@DIGEST]. */
import { useEffect, useState } from "react";
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, List, ListItemButton, ListItemText, Stack, Typography } from "@mui/material";
import * as ar from "../artifacts/api.js";
import { getProject } from "../../project.js";

const dec = (s) => { try { return decodeURIComponent(s); } catch { return s; } };

export default function ImagePicker({ open, onClose, onPick }) {
  const [repos, setRepos] = useState(null);
  const [repo, setRepo] = useState(null);
  const [pkgs, setPkgs] = useState(null);
  const [pkg, setPkg] = useState(null);
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    if (!open) return;
    setRepo(null); setPkg(null); setPkgs(null); setItems(null); setError(null);
    ar.listRepositories().then((r) => setRepos(r.filter((x) => x.format === "DOCKER"))).catch(setError);
  }, [open]);
  const pickRepo = (r) => { setRepo(r); setPkg(null); setItems(null); setPkgs(null); ar.listPackages(r.location, r.id).then(setPkgs).catch(setError); };
  const pickPkg = (p) => {
    setPkg(p); setItems(null);
    const id = ar.pkgIdOf(p);
    Promise.all([ar.listVersions(repo.location, repo.id, id), ar.listTags(repo.location, repo.id, id)])
      .then(([versions, tags]) => setItems(versions.map((v) => ({ digest: ar.versionIdOf(v), tags: tags.filter((t) => t.version === v.name).map(ar.tagIdOf) }))))
      .catch(setError);
  };
  const ref = (digestOrTag, isTag) => `${repo.location}-docker.pkg.dev/${getProject()}/${repo.id}/${dec(ar.pkgIdOf(pkg))}${isTag ? ":" : "@"}${digestOrTag}`;
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth aria-label="Select container image">
      <DialogTitle>Select container image</DialogTitle>
      <DialogContent>
        <Stack spacing={1}>
          {error && <Alert severity="error">{error.message}</Alert>}
          {!repo && (repos == null ? <Typography variant="body2">Loading repositories…</Typography>
            : repos.length === 0 ? <Typography variant="body2" color="text.secondary">No Docker repositories in this project. Create one in Artifact Registry and push an image first.</Typography>
            : <List dense aria-label="Repositories">{repos.map((r) => <ListItemButton key={r.name} onClick={() => pickRepo(r)}><ListItemText primary={r.id} secondary={r.location} /></ListItemButton>)}</List>)}
          {repo && !pkg && (<>
            <Typography variant="body2">Repository <b>{repo.id}</b></Typography>
            {pkgs == null ? <Typography variant="body2">Loading images…</Typography>
              : pkgs.length === 0 ? <Typography variant="body2" color="text.secondary">This repository has no images.</Typography>
              : <List dense aria-label="Images">{pkgs.map((p) => <ListItemButton key={p.name} onClick={() => pickPkg(p)}><ListItemText primary={dec(ar.pkgIdOf(p))} /></ListItemButton>)}</List>}
          </>)}
          {pkg && (<>
            <Typography variant="body2">Image <b>{dec(ar.pkgIdOf(pkg))}</b></Typography>
            {items == null ? <Typography variant="body2">Loading…</Typography> : (
              <List dense aria-label="Image versions">{items.map((it) => (
                <ListItemButton key={it.digest} onClick={() => { onPick(ref(it.tags[0] || it.digest, !!it.tags[0])); onClose(); }}>
                  <ListItemText primary={it.tags.length ? it.tags.join(", ") : "(untagged)"} secondary={it.digest} />
                </ListItemButton>))}</List>)}
          </>)}
        </Stack>
      </DialogContent>
      <DialogActions>{(repo || pkg) && <Button onClick={() => (pkg ? setPkg(null) : setRepo(null))}>Back</Button>}<Button onClick={onClose}>Cancel</Button></DialogActions>
    </Dialog>
  );
}
