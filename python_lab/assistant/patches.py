"""Versioned, single-source patch preview and confirmed replacement."""

from dataclasses import asdict
import difflib
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from uuid import uuid4

from python_lab.assistant.errors import AssistantError, ContextError
from python_lab.assistant.models import FileChange, PatchProposal
from python_lab.workspace import Workspace


class PatchService:
    def __init__(self, workspace: Workspace, data_dir: Path):
        if not isinstance(workspace, Workspace):
            raise AssistantError("Workspace inválido.")
        self.workspace = workspace
        self.data_dir = Path(data_dir)

    def _private_directory(self, path: Path) -> None:
        # A caller may choose an existing shared parent; protect our children
        # without changing permissions of a directory we did not create.
        try:
            self.data_dir.mkdir(mode=0o700, parents=True)
        except FileExistsError:
            if not self.data_dir.is_dir():
                raise
        else:
            self.data_dir.chmod(0o700)
        if path.is_symlink():
            raise OSError("Diretório de estado não pode ser symlink.")
        path.mkdir(mode=0o700, exist_ok=True)
        if path.is_symlink():
            raise OSError("Diretório de estado mudou de destino.")
        path.chmod(0o700)

    @staticmethod
    def _set_file_mode(fd: int, path: Path, mode: int) -> None:
        fchmod = getattr(os, "fchmod", None)
        if fchmod is not None:
            fchmod(fd, mode)
        else:
            path.chmod(mode)

    def _record_path(self, proposal_id: str) -> Path:
        if not isinstance(proposal_id, str) or not proposal_id:
            raise AssistantError("ID de proposta inválido.")
        try:
            key = hashlib.sha256(proposal_id.encode("utf-8")).hexdigest()
        except UnicodeEncodeError as exc:
            raise AssistantError("ID de proposta inválido.") from exc
        return self.data_dir / "proposals" / f"{key}.json"

    def _capture(self, proposal: PatchProposal):
        if not isinstance(proposal, PatchProposal):
            raise AssistantError("Proposta inválida.")
        try:
            snapshot = self.workspace.snapshot([Path(path) for path in proposal.selected_paths])
        except ContextError as exc:
            raise AssistantError(f"Fontes selecionadas indisponíveis: {exc}") from exc
        canonical = tuple(source.path for source in snapshot.sources)
        if canonical != proposal.selected_paths:
            raise AssistantError("Fontes selecionadas mudaram de destino.")
        source = next((source for source in snapshot.sources if source.path == proposal.change.path), None)
        if source is None:
            raise AssistantError("Destino não pertence às fontes selecionadas.")
        if source.sha256 != proposal.change.before_sha256:
            raise AssistantError("Arquivo alterado; capture novo snapshot e crie outra proposta.")
        return source

    def _saved(self, proposal: PatchProposal) -> None:
        record = self._record_path(proposal.id)
        if record.exists():
            if self.load(proposal.id) != proposal:
                raise AssistantError("ID de proposta já pertence a outra proposta ou workspace.")

    def preview(self, proposal: PatchProposal) -> str:
        self._saved(proposal)
        source = self._capture(proposal)
        lines = difflib.unified_diff(
            source.text.splitlines(keepends=True),
            proposal.change.after_text.splitlines(keepends=True),
            fromfile=f"a/{source.path}", tofile=f"b/{source.path}",
        )
        return "".join(
            line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
            for line in lines
        )

    def save(self, proposal: PatchProposal) -> None:
        self._capture(proposal)
        self._saved(proposal)
        path = self._record_path(proposal.id)
        if path.exists():
            return
        payload = {"workspace": str(self.workspace.root), "proposal": asdict(proposal)}
        temporary = None
        try:
            self._private_directory(path.parent)
            fd, name = tempfile.mkstemp(prefix=".python-lab-proposal-", dir=path.parent)
            temporary = Path(name)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                self._set_file_mode(stream.fileno(), temporary, 0o600)
                json.dump(payload, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            # Publishing a complete record via hard link never replaces another ID owner.
            try:
                os.link(temporary, path)
            except FileExistsError:
                if self.load(proposal.id) != proposal:
                    raise AssistantError("ID de proposta já pertence a outra proposta ou workspace.")
        except (OSError, TypeError, ValueError) as exc:
            raise AssistantError("Não foi possível salvar a proposta.") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def load(self, proposal_id: str) -> PatchProposal:
        path = self._record_path(proposal_id)
        try:
            with path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
            if payload["workspace"] != str(self.workspace.root):
                raise AssistantError("Proposta pertence a outro workspace.")
            raw = payload["proposal"]
            proposal = PatchProposal(
                raw["id"], FileChange(**raw["change"]), raw["reason"], tuple(raw["selected_paths"]),
            )
            if proposal.id != proposal_id:
                raise AssistantError("ID de proposta não corresponde ao registro.")
            return proposal
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise AssistantError("Proposta desconhecida ou inválida.") from exc

    def apply(self, proposal: PatchProposal, *, confirmed: bool) -> Path:
        if confirmed is not True:
            raise AssistantError("Aplicação exige confirmação explícita.")
        self._saved(proposal)
        source = self._capture(proposal)
        destination = self.workspace.root / source.path
        old_bytes = source.text.encode("utf-8")
        new_bytes = proposal.change.after_text.encode("utf-8")
        backup_path = self.data_dir / "backups" / (
            f"{hashlib.sha256(proposal.id.encode('utf-8')).hexdigest()}-{uuid4().hex}.bak"
        )
        backup_created = False
        try:
            self._private_directory(backup_path.parent)
            fd = os.open(backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            backup_created = True
            with os.fdopen(fd, "wb") as backup:
                self._set_file_mode(backup.fileno(), backup_path, 0o600)
                backup.write(old_bytes)
                backup.flush()
                os.fsync(backup.fileno())
        except OSError as exc:
            if backup_created:
                backup_path.unlink(missing_ok=True)
            raise AssistantError("Falha ao criar backup; arquivo original preservado.") from exc

        temp_path = None
        try:
            mode = stat.S_IMODE(destination.stat().st_mode)
            fd, temp_name = tempfile.mkstemp(prefix=".python-lab-patch-", dir=destination.parent)
            temp_path = Path(temp_name)
            with os.fdopen(fd, "wb") as temp:
                temp.write(new_bytes)
                temp.flush()
                self._set_file_mode(temp.fileno(), temp_path, mode)
                os.fsync(temp.fileno())
            # Recheck after both backup and temporary write, immediately before rename.
            self._saved(proposal)
            self._capture(proposal)
            os.replace(temp_path, destination)
            temp_path = None
        except (OSError, AssistantError) as exc:
            if isinstance(exc, AssistantError):
                raise
            raise AssistantError(
                f"Falha ao substituir arquivo; verifique o destino. Backup: {backup_path}"
            ) from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
        return destination
