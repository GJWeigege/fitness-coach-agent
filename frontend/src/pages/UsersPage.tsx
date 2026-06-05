import { useUsers } from "../hooks/useUsers";
import { Button } from "../components/ui/Button";
import { Badge, roleVariant } from "../components/ui/Badge";
import { ShieldIcon } from "../components/ui/Icons";

export function UsersPage() {
  const users = useUsers();

  return (
    <section className="panel">
      <div className="panel__header">
        <div>
          <h3>用户与权限管理</h3>
          <p>管理系统用户角色与访问权限</p>
        </div>
      </div>

      <form onSubmit={(e) => void users.create(e)} className="inline-form">
        <input placeholder="用户名" value={users.newUserName} onChange={(e) => users.setNewUserName(e.target.value)} />
        <input
          placeholder="密码"
          value={users.newUserPassword}
          onChange={(e) => users.setNewUserPassword(e.target.value)}
          type="password"
        />
        <select value={users.newUserRole} onChange={(e) => users.setNewUserRole(e.target.value)}>
          {Object.keys(users.permissionMatrix).map((role) => (
            <option key={role} value={role}>
              {role}
            </option>
          ))}
        </select>
        <Button type="submit" variant="primary">
          创建用户
        </Button>
      </form>

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>用户名</th>
              <th>角色</th>
              <th>状态</th>
              <th>权限</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {users.users.map((user) => (
              <tr key={user.id}>
                <td>
                  <div className="user-cell">
                    <ShieldIcon />
                    <span>{user.username}</span>
                  </div>
                </td>
                <td>
                  <select value={user.role} onChange={(e) => void users.changeRole(user.id, e.target.value)}>
                    {Object.keys(users.permissionMatrix).map((role) => (
                      <option key={role} value={role}>
                        {role}
                      </option>
                    ))}
                  </select>
                  <Badge variant={roleVariant(user.role)}>{user.role}</Badge>
                </td>
                <td>
                  <Badge variant={user.is_active ? "success" : "danger"}>{user.is_active ? "启用" : "禁用"}</Badge>
                </td>
                <td className="data-table__permissions">{user.permissions.join(", ")}</td>
                <td>
                  <Button variant="ghost" onClick={() => void users.toggleActive(user.id, !user.is_active)}>
                    {user.is_active ? "禁用" : "启用"}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
