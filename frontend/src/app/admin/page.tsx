"use client";

import { useEffect, useState } from "react";
import {
  Download,
  FileText,
  Loader2,
  LogOut,
  MessageSquare,
  ShieldCheck,
  Users,
} from "lucide-react";
import {
  ApiError,
  adminApi,
  getAdminToken,
  type AdminUserActivity,
  type AdminUserSummary,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

function fmt(ts: string | null | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts);
  return isNaN(d.getTime()) ? String(ts) : d.toLocaleString();
}

export default function AdminPage() {
  const [authed, setAuthed] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setAuthed(!!getAdminToken());
    setMounted(true);
  }, []);

  if (!mounted) return null;

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-ink-deep text-paper">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-lg font-semibold">Admin console</h1>
            <p className="text-xs text-muted-foreground">
              Compliance view — users and their activity trail
            </p>
          </div>
        </div>
        {authed && (
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={() => {
              adminApi.logout();
              setAuthed(false);
            }}
          >
            <LogOut className="h-3.5 w-3.5" />
            Log out
          </Button>
        )}
      </div>

      {authed ? (
        <AdminDashboard onUnauthorized={() => setAuthed(false)} />
      ) : (
        <AdminLogin onSuccess={() => setAuthed(true)} />
      )}
    </div>
  );
}

function AdminLogin({ onSuccess }: { onSuccess: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await adminApi.login(username, password);
      onSuccess();
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "Invalid admin credentials."
          : "Login failed — is the backend running?",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mx-auto max-w-sm">
      <CardHeader>
        <CardTitle className="text-base">Administrator sign in</CardTitle>
        <p className="text-xs text-muted-foreground">
          Restricted area. All access is for compliance review only.
        </p>
      </CardHeader>
      <CardContent>
        <form className="flex flex-col gap-3" onSubmit={submit}>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="admin-user">Username</Label>
            <Input
              id="admin-user"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="off"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="admin-pass">Password</Label>
            <Input
              id="admin-pass"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="off"
            />
          </div>
          {error && <p className="text-xs text-red-600">{error}</p>}
          <Button type="submit" disabled={busy || !username || !password}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Sign in"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function AdminDashboard({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [users, setUsers] = useState<AdminUserSummary[] | null>(null);
  const [selected, setSelected] = useState<AdminUserSummary | null>(null);
  const [activity, setActivity] = useState<AdminUserActivity | null>(null);
  const [loadingActivity, setLoadingActivity] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleError = (err: unknown) => {
    if (err instanceof ApiError && err.status === 401) {
      adminApi.logout();
      onUnauthorized();
      return;
    }
    setError(err instanceof Error ? err.message : "Request failed");
  };

  useEffect(() => {
    adminApi.users().then(setUsers).catch(handleError);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function openUser(u: AdminUserSummary) {
    setSelected(u);
    setActivity(null);
    setLoadingActivity(true);
    try {
      setActivity(await adminApi.userActivity(u.id));
    } catch (err) {
      handleError(err);
    } finally {
      setLoadingActivity(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {error && <p className="text-sm text-red-600">{error}</p>}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Users className="h-4 w-4" />
            Users{users ? ` (${users.length})` : ""}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {users === null ? (
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Username</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Registered</TableHead>
                    <TableHead className="text-right">Projects</TableHead>
                    <TableHead className="text-right">Documents</TableHead>
                    <TableHead className="text-right">Duty calcs</TableHead>
                    <TableHead className="text-right">Chats</TableHead>
                    <TableHead className="text-right">Actions logged</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.map((u) => (
                    <TableRow
                      key={u.id}
                      className={cn(
                        "cursor-pointer",
                        selected?.id === u.id && "bg-muted/50",
                      )}
                      onClick={() => void openUser(u)}
                    >
                      <TableCell className="font-medium">
                        {u.display_name ?? "—"}
                      </TableCell>
                      <TableCell>{u.email}</TableCell>
                      <TableCell>{fmt(u.created_at)}</TableCell>
                      <TableCell className="text-right">
                        {u.counts.projects}
                      </TableCell>
                      <TableCell className="text-right">
                        {u.counts.documents + u.counts.library_documents}
                      </TableCell>
                      <TableCell className="text-right">
                        {u.counts.duty_calculations}
                      </TableCell>
                      <TableCell className="text-right">
                        {u.counts.chat_messages}
                      </TableCell>
                      <TableCell className="text-right">
                        {u.counts.audit_events}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {selected && (
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle className="text-base">
                {selected.display_name ?? selected.email}
              </CardTitle>
              <p className="text-xs text-muted-foreground">
                {selected.email} · registered {fmt(selected.created_at)}
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() =>
                void adminApi
                  .downloadActivityCsv(selected.id, selected.email)
                  .catch(handleError)
              }
            >
              <Download className="h-3.5 w-3.5" />
              Export CSV for tax file
            </Button>
          </CardHeader>
          <CardContent>
            {loadingActivity ? (
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            ) : activity ? (
              <ActivityDetail activity={activity} />
            ) : null}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function ActivityDetail({ activity }: { activity: AdminUserActivity }) {
  return (
    <div className="flex flex-col gap-6">
      {/* Action trail */}
      <section>
        <h3 className="mb-2 text-sm font-semibold">
          Action trail ({activity.events.length})
        </h3>
        {activity.events.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No audited actions yet — the trail records everything from now on.
          </p>
        ) : (
          <div className="max-h-80 overflow-auto rounded-lg border border-border/60">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Request</TableHead>
                  <TableHead className="text-right">Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {activity.events.map((e, i) => (
                  <TableRow key={i}>
                    <TableCell className="whitespace-nowrap text-xs">
                      {fmt(e.created_at)}
                    </TableCell>
                    <TableCell className="text-xs font-medium">
                      {e.action}
                    </TableCell>
                    <TableCell className="max-w-[280px] truncate font-data text-[11px] text-muted-foreground">
                      {e.method} {e.path}
                      {e.query ? `?${e.query}` : ""}
                    </TableCell>
                    <TableCell className="text-right">
                      <Badge
                        variant={e.status_code < 400 ? "ok" : "gap"}
                        className="text-[10px]"
                      >
                        {e.status_code}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Uploaded documents */}
        <section>
          <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
            <FileText className="h-4 w-4" />
            Uploaded documents (
            {activity.documents.length + activity.library_documents.length})
          </h3>
          <div className="max-h-72 overflow-auto rounded-lg border border-border/60">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>File</TableHead>
                  <TableHead>Where</TableHead>
                  <TableHead>Uploaded</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {activity.library_documents.map((d) => (
                  <TableRow key={d.id}>
                    <TableCell className="max-w-[220px] truncate text-xs">
                      {d.filename}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      Library
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs">
                      {fmt(d.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
                {activity.documents.map((d) => (
                  <TableRow key={d.id}>
                    <TableCell className="max-w-[220px] truncate text-xs">
                      {d.filename}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      Project: {d.project ?? "—"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs">
                      {fmt(d.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
                {activity.documents.length === 0 &&
                  activity.library_documents.length === 0 && (
                    <TableRow>
                      <TableCell
                        colSpan={3}
                        className="text-xs text-muted-foreground"
                      >
                        No documents uploaded.
                      </TableCell>
                    </TableRow>
                  )}
              </TableBody>
            </Table>
          </div>
        </section>

        {/* Chat messages */}
        <section>
          <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
            <MessageSquare className="h-4 w-4" />
            Chat messages ({activity.chat_messages.length})
          </h3>
          <div className="max-h-72 overflow-auto rounded-lg border border-border/60 p-3">
            {activity.chat_messages.length === 0 ? (
              <p className="text-xs text-muted-foreground">No chat messages.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {activity.chat_messages.map((m, i) => (
                  <li key={i} className="text-xs">
                    <span className="text-muted-foreground">
                      {fmt(m.created_at)} —{" "}
                    </span>
                    {m.content}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>

      {/* Projects */}
      <section>
        <h3 className="mb-2 text-sm font-semibold">
          Projects ({activity.projects.length})
        </h3>
        {activity.projects.length === 0 ? (
          <p className="text-xs text-muted-foreground">No projects.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {activity.projects.map((p) => (
              <Badge key={p.id} variant="verify" className="text-[11px]">
                {p.name} · {p.status} · {fmt(p.created_at)}
              </Badge>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
