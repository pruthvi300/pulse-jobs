import axios from 'axios';

const http = axios.create({
  baseURL: `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/v1/jobs`,
  timeout: 10000,
});

export function errorMessage(error) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join('; ');
  return error?.message || 'Request failed';
}

export const getStats = () => http.get('/stats/summary').then((r) => r.data);
export const listJobs = (params) => http.get('/', { params }).then((r) => r.data);
export const createJob = (body) => http.post('/', body).then((r) => r.data);
export const retryJob = (id) => http.post(`/${id}/retry`).then((r) => r.data);
