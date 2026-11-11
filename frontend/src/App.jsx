import { useCallback, useEffect, useState } from 'react';
import { createJob, errorMessage, getStats, listJobs, retryJob } from './api';

const SAMPLE_PAYLOADS = {
  send_email: { to: 'test@example.com', subject: 'Test Email', body: 'Hello!' },
  generate_report: { report_type: 'monthly', params: { month: 'January' } },
  process_webhook: { webhook_url: 'https://example.com/webhook', payload: { event: 'test' } },
  process_image: { image_url: 'https://example.com/image.jpg', operations: ['resize', 'compress'] },
};

const TASK_BUTTONS = [
  ['send_email', '📧 Send Email'],
  ['generate_report', '📊 Generate Report'],
  ['process_webhook', '🔗 Webhook'],
  ['process_image', '🖼️ Process Image'],
];

const STAT_CARDS = [
  ['total_jobs', 'Total Jobs', ''],
  ['pending', 'Pending', 'pending'],
  ['running', 'Running', 'running'],
  ['retrying', 'Retrying', 'retrying'],
  ['completed', 'Completed', 'completed'],
  ['failed', 'Failed', 'failed'],
  ['dead_letter', 'Dead Letter', 'dead_letter'],
];

const STATUSES = ['pending', 'running', 'retrying', 'completed', 'failed', 'dead_letter'];
const REFRESH_MS = 3000;

function App() {
  const [stats, setStats] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [statusFilter, setStatusFilter] = useState('');
  const [priority, setPriority] = useState('default');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const params = { page_size: 15, ...(statusFilter && { status: statusFilter }) };
      const [s, j] = await Promise.all([getStats(), listJobs(params)]);
      setStats(s);
      setJobs(j.jobs);
      setError(null);
    } catch (e) {
      setError(`Could not load jobs: ${errorMessage(e)}`);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, REFRESH_MS);
    return () => clearInterval(interval);
  }, [fetchData]);

  const run = async (action) => {
    setBusy(true);
    try {
      await action();
      await fetchData();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const submitJob = (taskName) =>
    run(() =>
      createJob({
        task_name: taskName,
        payload: SAMPLE_PAYLOADS[taskName],
        priority,
        idempotency_key: `${taskName}-${crypto.randomUUID()}`,
      }),
    );

  const formatDate = (iso) => (iso ? new Date(iso).toLocaleString() : '-');

  if (loading) {
    return (
      <div className="app">
        <div className="loading">Loading dashboard...</div>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="header">
        <div className="logo">
          <div className="logo-icon">⚡</div>
          <div>
            <h1>Pulse</h1>
            <span>Job Processing Dashboard</span>
          </div>
        </div>
        <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>Auto-refreshing every 3s</div>
      </header>

      {error && <div className="error-banner" role="alert">{error}</div>}

      {stats && (
        <div className="stats-grid">
          {STAT_CARDS.map(([key, label, cls]) => (
            <div key={key} className={`stat-card ${cls}`}>
              <h3>{label}</h3>
              <div className="value">{stats[key]}</div>
            </div>
          ))}
        </div>
      )}

      <div className="actions-panel">
        <span style={{ color: 'var(--text-secondary)', marginRight: '1rem' }}>Submit test job:</span>
        <div className="filters" style={{ marginBottom: 0 }}>
          <select value={priority} onChange={(e) => setPriority(e.target.value)} aria-label="Priority">
            {['critical', 'high', 'default', 'low'].map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
          {TASK_BUTTONS.map(([task, label]) => (
            <button key={task} className="btn btn-secondary" onClick={() => submitJob(task)} disabled={busy}>
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="jobs-section">
        <h2>📋 Recent Jobs</h2>
        <div className="filters">
          <label htmlFor="status-filter" style={{ color: 'var(--text-secondary)' }}>Status</label>
          <select id="status-filter" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">all</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{s.replace('_', ' ')}</option>
            ))}
          </select>
        </div>

        {jobs.length === 0 ? (
          <div className="empty-state">
            <p>No jobs here yet. Submit a test job above!</p>
          </div>
        ) : (
          <table className="jobs-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Task</th>
                <th>Status</th>
                <th>Priority</th>
                <th>Attempts</th>
                <th>Last error</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id}>
                  <td>#{job.id}</td>
                  <td className="task-name">{job.task_name}</td>
                  <td>
                    <span className={`status-badge ${job.status}`}>{job.status.replace('_', ' ')}</span>
                  </td>
                  <td>{job.priority}</td>
                  <td>{job.attempts} / {job.max_retries + 1}</td>
                  <td className="error-text" title={job.error_message || ''}>{job.error_message || '-'}</td>
                  <td className="timestamp">{formatDate(job.created_at)}</td>
                  <td>
                    {(job.status === 'failed' || job.status === 'dead_letter') && (
                      <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => run(() => retryJob(job.id))}>
                        Retry
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export default App;
