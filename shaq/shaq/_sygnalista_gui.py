from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable, Literal

ReportKind = Literal["bug", "suggestion"]

DEFAULT_SYGNALISTA_BASE_URL = "https://sygnalista.michaldziwisz.workers.dev"


def sygnalista_base_url() -> str:
    value = str(os.environ.get("SYGNALISTA_BASE_URL") or "").strip()
    return value or DEFAULT_SYGNALISTA_BASE_URL


def _write_temp_json(payload: Any) -> Path:
    with NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".json") as tmp:
        json.dump(payload, tmp, ensure_ascii=False, indent=2, sort_keys=True)
        return Path(tmp.name)


def show_sygnalista_report_dialog(
    parent: Any,
    *,
    t: Any,
    app_name: str,
    app_id: str,
    app_version: str | None,
    diagnostics_extra_provider: Callable[[], dict[str, Any]] | None = None,
    log_payload_provider: Callable[[], dict[str, Any]] | None = None,
) -> None:
    import wx

    class _ReportDialog(wx.Dialog):
        def __init__(self) -> None:
            super().__init__(parent, title=t("dialog.report.title"))
            self._sending = False

            panel = wx.Panel(self)

            kind_label = wx.StaticText(panel, label=t("label.report_kind"))
            self.kind_choice = wx.Choice(
                panel,
                choices=[t("choice.report_kind_bug"), t("choice.report_kind_suggestion")],
            )
            self.kind_choice.SetName(t("name.report_kind"))
            self.kind_choice.SetSelection(0)

            title_label = wx.StaticText(panel, label=t("label.report_title"))
            self.title_ctrl = wx.TextCtrl(panel)
            self.title_ctrl.SetName(t("name.report_title"))

            desc_label = wx.StaticText(panel, label=t("label.report_description"))
            self.desc_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE)
            self.desc_ctrl.SetName(t("name.report_description"))

            email_label = wx.StaticText(panel, label=t("label.report_email"))
            self.email_ctrl = wx.TextCtrl(panel)
            self.email_ctrl.SetName(t("name.report_email"))

            email_help = wx.StaticText(panel, label=t("help.report_email_public"))

            self.include_logs_cb = wx.CheckBox(panel, label=t("label.report_include_logs"))
            self.include_logs_cb.SetName(t("name.report_include_logs"))

            self.status = wx.StaticText(panel, label="")

            self.send_btn = wx.Button(panel, label=t("button.report_send"))
            self.send_btn.SetName(t("name.report_send"))
            self.cancel_btn = wx.Button(panel, label=t("button.cancel"))
            self.cancel_btn.SetName(t("name.report_cancel"))

            btn_row = wx.BoxSizer(wx.HORIZONTAL)
            btn_row.AddStretchSpacer(1)
            btn_row.Add(self.send_btn, 0, wx.RIGHT, 8)
            btn_row.Add(self.cancel_btn, 0)

            form = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
            form.AddGrowableCol(1, 1)
            form.Add(kind_label, 0, wx.ALIGN_CENTER_VERTICAL)
            form.Add(self.kind_choice, 1, wx.EXPAND)
            form.Add(title_label, 0, wx.ALIGN_CENTER_VERTICAL)
            form.Add(self.title_ctrl, 1, wx.EXPAND)
            form.Add(desc_label, 0, wx.ALIGN_TOP)
            form.Add(self.desc_ctrl, 1, wx.EXPAND)
            form.Add(email_label, 0, wx.ALIGN_CENTER_VERTICAL)
            form.Add(self.email_ctrl, 1, wx.EXPAND)

            root = wx.BoxSizer(wx.VERTICAL)
            root.Add(form, 1, wx.ALL | wx.EXPAND, 12)
            root.Add(email_help, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
            root.Add(self.include_logs_cb, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
            root.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
            root.Add(btn_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
            panel.SetSizer(root)

            self.SetMinClientSize((640, 460))
            self.CenterOnParent()

            self.send_btn.Bind(wx.EVT_BUTTON, self._on_send)
            self.cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)
            self.Bind(wx.EVT_CLOSE, self._on_close)

        def _set_sending(self, sending: bool) -> None:
            self._sending = sending
            self.kind_choice.Enable(not sending)
            self.title_ctrl.Enable(not sending)
            self.desc_ctrl.Enable(not sending)
            self.email_ctrl.Enable(not sending)
            self.include_logs_cb.Enable(not sending)
            self.send_btn.Enable(not sending)
            self.cancel_btn.Enable(not sending)

        def _on_close(self, event: wx.CloseEvent) -> None:
            if self._sending:
                return
            event.Skip()

        def _on_cancel(self, _event: wx.CommandEvent) -> None:
            if self._sending:
                return
            self.EndModal(wx.ID_CANCEL)

        def _on_send(self, _event: wx.CommandEvent) -> None:
            title = self.title_ctrl.GetValue().strip()
            if not title:
                wx.MessageBox(t("error.report_title_required"), app_name, wx.OK | wx.ICON_ERROR, self)
                return

            description = self.desc_ctrl.GetValue().strip()
            if not description:
                wx.MessageBox(
                    t("error.report_description_required"),
                    app_name,
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
                return

            kind_idx = self.kind_choice.GetSelection()
            kind: ReportKind = "suggestion" if kind_idx == 1 else "bug"

            email = self.email_ctrl.GetValue().strip() or None
            include_logs = bool(self.include_logs_cb.GetValue())

            self.status.SetLabel(t("status.report_sending"))
            self._set_sending(True)

            def _worker() -> None:
                temp_payload_path: Path | None = None
                try:
                    try:
                        from sygnalista_reporter import ReportError, send_report
                    except Exception as exc:
                        raise RuntimeError(t("error.report_not_available", error=str(exc))) from exc

                    diagnostics_extra = (
                        diagnostics_extra_provider() if diagnostics_extra_provider else None
                    )

                    log_path: str | None = None
                    if include_logs and log_payload_provider:
                        payload = log_payload_provider()
                        temp_payload_path = _write_temp_json(payload)
                        log_path = str(temp_payload_path)

                    try:
                        result = send_report(
                            base_url=sygnalista_base_url(),
                            app_id=app_id,
                            app_version=app_version,
                            kind=kind,
                            title=title,
                            description=description,
                            email=email,
                            log_path=log_path,
                            diagnostics_extra=diagnostics_extra,
                        )
                    except ReportError as exc:
                        message = str(exc).strip() or "Report failed"
                        status = getattr(exc, "status", None)
                        payload = getattr(exc, "payload", None)
                        if isinstance(payload, dict):
                            err = payload.get("error")
                            if isinstance(err, dict) and isinstance(err.get("message"), str):
                                message = err["message"]
                        if status:
                            message = f"HTTP {status}: {message}"
                        wx.CallAfter(self._on_send_failed, message)
                        return
                    except Exception as exc:
                        message = str(exc).strip() or repr(exc)
                        wx.CallAfter(self._on_send_failed, message)
                        return
                except Exception as exc:
                    message = str(exc).strip() or repr(exc)
                    wx.CallAfter(self._on_send_failed, message)
                    return
                else:
                    wx.CallAfter(self._on_send_ok, result)
                finally:
                    if temp_payload_path is not None:
                        try:
                            temp_payload_path.unlink(missing_ok=True)
                        except Exception:
                            pass

            threading.Thread(target=_worker, daemon=True).start()

        def _on_send_ok(self, result: Any) -> None:
            self._set_sending(False)

            issue_url = ""
            if isinstance(result, dict):
                issue = result.get("issue")
                if isinstance(issue, dict) and isinstance(issue.get("html_url"), str):
                    issue_url = issue["html_url"]

            wx.MessageBox(t("info.report_sent", url=issue_url or "?"), app_name, wx.OK, self)
            self.EndModal(wx.ID_OK)

        def _on_send_failed(self, message: str) -> None:
            self._set_sending(False)
            self.status.SetLabel("")
            wx.MessageBox(t("error.report_failed", error=message), app_name, wx.OK | wx.ICON_ERROR, self)

    dlg = _ReportDialog()
    try:
        dlg.ShowModal()
    finally:
        dlg.Destroy()
