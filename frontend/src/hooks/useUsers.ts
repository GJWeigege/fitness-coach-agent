import { useCallback, useEffect, useState } from "react";
import { createUser, fetchUsers, updateUser } from "../api";
import { useAuth, usePermissions } from "../contexts/AuthContext";
import { useApp } from "../contexts/AppContext";
import type { UserProfile } from "../types";

export function useUsers() {
  const { token, permissionMatrix } = useAuth();
  const { canManageUsers } = usePermissions();
  const { setError } = useApp();
  const [users, setUsers] = useState<UserProfile[]>([]);
  const [newUserName, setNewUserName] = useState("");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [newUserRole, setNewUserRole] = useState("user");

  const loadUsers = useCallback(async () => {
    if (!token || !canManageUsers) return;
    try {
      setUsers(await fetchUsers(token));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [token, canManageUsers, setError]);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!token) return;
    try {
      await createUser(token, { username: newUserName, password: newUserPassword, role: newUserRole });
      setNewUserName("");
      setNewUserPassword("");
      await loadUsers();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function changeRole(userId: string, role: string) {
    if (!token) return;
    try {
      await updateUser(token, userId, { role });
      await loadUsers();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function toggleActive(userId: string, active: boolean) {
    if (!token) return;
    try {
      await updateUser(token, userId, { is_active: active });
      await loadUsers();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return {
    users,
    permissionMatrix,
    newUserName,
    setNewUserName,
    newUserPassword,
    setNewUserPassword,
    newUserRole,
    setNewUserRole,
    loadUsers,
    create,
    changeRole,
    toggleActive,
  };
}
