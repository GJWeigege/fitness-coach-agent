import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  createTrainingLog,
  fetchProfile,
  listTrainingLogs,
  updateProfile,
  type FitnessProfile,
  type TrainingLog,
} from "../api/profile";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { useAuth } from "../contexts/AuthContext";

function parseListInput(value: string): string[] | null {
  const items = value
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
  return items.length ? items : null;
}

function formatListInput(value: string[] | null | undefined): string {
  return value?.join(", ") ?? "";
}

function toNumberOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

export function ProfilePage() {
  const { token } = useAuth();
  const [profile, setProfile] = useState<FitnessProfile | null>(null);
  const [logs, setLogs] = useState<TrainingLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [addingLog, setAddingLog] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  const [age, setAge] = useState("");
  const [sex, setSex] = useState("");
  const [heightCm, setHeightCm] = useState("");
  const [weightKg, setWeightKg] = useState("");
  const [goals, setGoals] = useState("");
  const [experienceLevel, setExperienceLevel] = useState("beginner");
  const [injuries, setInjuries] = useState("");
  const [equipment, setEquipment] = useState("");
  const [dietPreference, setDietPreference] = useState("");

  const [logDate, setLogDate] = useState("");
  const [logActivity, setLogActivity] = useState("");
  const [logDuration, setLogDuration] = useState("");
  const [logIntensity, setLogIntensity] = useState("moderate");
  const [logNotes, setLogNotes] = useState("");

  function applyProfile(data: FitnessProfile) {
    setProfile(data);
    setAge(data.age != null ? String(data.age) : "");
    setSex(data.sex ?? "");
    setHeightCm(data.height_cm != null ? String(data.height_cm) : "");
    setWeightKg(data.weight_kg != null ? String(data.weight_kg) : "");
    setGoals(formatListInput(data.goals));
    setExperienceLevel(data.experience_level || "beginner");
    setInjuries(formatListInput(data.injuries));
    setEquipment(formatListInput(data.equipment));
    setDietPreference(data.diet_preference ?? "");
  }

  const loadData = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      const [profileData, logData] = await Promise.all([fetchProfile(token), listTrainingLogs(token)]);
      applyProfile(profileData);
      setLogs(logData);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  async function onSaveProfile(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    setSaving(true);
    setError("");
    setStatus("");
    try {
      const updated = await updateProfile(token, {
        age: toNumberOrNull(age) != null ? Math.trunc(toNumberOrNull(age)!) : null,
        sex: sex.trim() || null,
        height_cm: toNumberOrNull(heightCm),
        weight_kg: toNumberOrNull(weightKg),
        goals: parseListInput(goals),
        experience_level: experienceLevel,
        injuries: parseListInput(injuries),
        equipment: parseListInput(equipment),
        diet_preference: dietPreference.trim() || null,
      });
      applyProfile(updated);
      setStatus("档案已保存");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function onAddLog(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    const duration = toNumberOrNull(logDuration);
    if (!logDate || !logActivity.trim() || duration == null || duration < 1) {
      setError("请填写完整的训练记录（日期、类型、时长）。");
      return;
    }
    setAddingLog(true);
    setError("");
    setStatus("");
    try {
      const created = await createTrainingLog(token, {
        session_date: logDate,
        activity_type: logActivity.trim(),
        duration_min: Math.trunc(duration),
        intensity: logIntensity,
        notes: logNotes.trim() || null,
      });
      setLogs((prev) => [created, ...prev]);
      setLogActivity("");
      setLogDuration("");
      setLogNotes("");
      setStatus("训练记录已添加");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAddingLog(false);
    }
  }

  if (loading) {
    return (
      <div className="page">
        <h1>健身档案</h1>
        <p>加载中…</p>
      </div>
    );
  }

  return (
    <div className="page profile-page">
      <div className="panel">
        <div className="panel__header">
          <div>
            <h3>健身档案</h3>
            <p>完善身体数据与训练目标，便于教练个性化建议</p>
          </div>
          <Button variant="secondary" onClick={() => void loadData()}>
            刷新
          </Button>
        </div>

        {error ? <p className="panel__error">{error}</p> : null}
        {status ? <p className="panel__status">{status}</p> : null}

        <form className="profile-form" onSubmit={onSaveProfile}>
          <div className="profile-form__grid">
            <label className="field">
              <span>年龄</span>
              <input value={age} onChange={(e) => setAge(e.target.value)} inputMode="numeric" placeholder="28" />
            </label>
            <label className="field">
              <span>性别</span>
              <select value={sex} onChange={(e) => setSex(e.target.value)}>
                <option value="">未设置</option>
                <option value="male">男</option>
                <option value="female">女</option>
                <option value="other">其他</option>
              </select>
            </label>
            <label className="field">
              <span>身高 (cm)</span>
              <input value={heightCm} onChange={(e) => setHeightCm(e.target.value)} inputMode="decimal" placeholder="175" />
            </label>
            <label className="field">
              <span>体重 (kg)</span>
              <input value={weightKg} onChange={(e) => setWeightKg(e.target.value)} inputMode="decimal" placeholder="70" />
            </label>
            <label className="field">
              <span>训练经验</span>
              <select value={experienceLevel} onChange={(e) => setExperienceLevel(e.target.value)}>
                <option value="beginner">初学者</option>
                <option value="intermediate">中级</option>
                <option value="advanced">高级</option>
              </select>
            </label>
            <label className="field">
              <span>饮食偏好</span>
              <input
                value={dietPreference}
                onChange={(e) => setDietPreference(e.target.value)}
                placeholder="如：高蛋白、低碳"
              />
            </label>
          </div>

          <label className="field">
            <span>目标（逗号分隔）</span>
            <input value={goals} onChange={(e) => setGoals(e.target.value)} placeholder="增肌, 减脂" />
          </label>
          <label className="field">
            <span>伤病 / 限制（逗号分隔）</span>
            <input value={injuries} onChange={(e) => setInjuries(e.target.value)} placeholder="左膝旧伤" />
          </label>
          <label className="field">
            <span>可用器械（逗号分隔）</span>
            <input value={equipment} onChange={(e) => setEquipment(e.target.value)} placeholder="哑铃, 跑步机" />
          </label>

          <div className="profile-form__actions">
            <Button type="submit" variant="primary" disabled={saving}>
              {saving ? "保存中…" : "保存档案"}
            </Button>
            {profile?.updated_at ? (
              <span className="profile-form__meta">上次更新：{new Date(profile.updated_at).toLocaleString()}</span>
            ) : null}
          </div>
        </form>
      </div>

      <section className="panel">
        <div className="panel__header">
          <div>
            <h3>训练记录</h3>
            <p>记录每次训练，便于跟踪恢复与负荷</p>
          </div>
        </div>

        <form className="profile-form profile-form--compact" onSubmit={onAddLog}>
          <div className="profile-form__grid">
            <label className="field">
              <span>日期</span>
              <input type="date" value={logDate} onChange={(e) => setLogDate(e.target.value)} required />
            </label>
            <label className="field">
              <span>类型</span>
              <input value={logActivity} onChange={(e) => setLogActivity(e.target.value)} placeholder="strength / run" required />
            </label>
            <label className="field">
              <span>时长 (分钟)</span>
              <input value={logDuration} onChange={(e) => setLogDuration(e.target.value)} inputMode="numeric" required />
            </label>
            <label className="field">
              <span>强度</span>
              <select value={logIntensity} onChange={(e) => setLogIntensity(e.target.value)}>
                <option value="easy">轻松</option>
                <option value="moderate">中等</option>
                <option value="hard">高强度</option>
              </select>
            </label>
          </div>
          <label className="field">
            <span>备注</span>
            <input value={logNotes} onChange={(e) => setLogNotes(e.target.value)} placeholder="如：深蹲 5x5" />
          </label>
          <div className="profile-form__actions">
            <Button type="submit" variant="primary" disabled={addingLog}>
              {addingLog ? "添加中…" : "添加记录"}
            </Button>
          </div>
        </form>

        {logs.length === 0 ? (
          <EmptyState
            icon={
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                <path d="M6 4h12v16H6z" />
                <path d="M9 8h6M9 12h6M9 16h4" />
              </svg>
            }
            title="暂无训练记录"
            description="添加第一条记录开始跟踪训练"
          />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>日期</th>
                  <th>类型</th>
                  <th>时长</th>
                  <th>强度</th>
                  <th>备注</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.id}>
                    <td>{log.session_date}</td>
                    <td>{log.activity_type}</td>
                    <td>{log.duration_min} 分钟</td>
                    <td>{log.intensity}</td>
                    <td className="data-table__title">{log.notes || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
