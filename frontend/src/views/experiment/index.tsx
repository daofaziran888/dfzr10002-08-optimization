import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { request } from '@/api/client'

const ENDPOINT = '/api/experiment'
const columns = [
  "实验编号",
  "实验名称",
  "分析数据集",
  "分组字段",
  "目标度量",
  "基准区间",
  "显著阈值",
  "实验状态"
]
const actions = [
  "启动实验",
  "结束实验",
  "关闭实验"
]
const statuses = [
  "草稿",
  "运行中",
  "已完成",
  "已关闭"
]

type Row = Record<string, string | number | null>

export default function ExperimentView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const filterFields = ["实验编号", "实验名称"]

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('分析实验列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '分析实验管理列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ values: { action } }),
      })
      if (!response.ok) {
        throw new Error('分析实验管理动作未生效，请稍后重试')
      }
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '分析实验管理操作失败')
    }
  }

  const running = rows.filter((row) => row.实验状态 === '运行中' || row.status === '运行中').length
  const finished = rows.filter((row) => row.实验状态 === '已完成' || row.status === '已完成').length

  return (
    <section className="page" data-module="experiment">
      <header className="page-head">
        <div>
          <h2>分析实验管理</h2>
          <p className="page-desc">维护分析实验的设计参数、分组方案与统计显著性校验，支持A/B实验分析。</p>
        </div>
        <div className="page-actions">
          <Link className="btn primary" to="/experiment-review">进入实验复核</Link>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出分析实验管理清单
          </button>
        </div>
      </header>

      <div className="stat-row">
        {[
          { label: '分析实验总数', value: total },
          { label: '运行中实验', value: running },
          { label: '已完成实验', value: finished },
        ].map((item) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
          </article>
        ))}
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        {filterFields.map((field) => (
          <label key={field} className="filter-item">
            <span>{field}</span>
            <input
              value={filters[field] ?? ''}
              placeholder={`按${field}检索`}
              onChange={(event) => setFilters((prev) => ({ ...prev, [field]: event.target.value }))}
            />
          </label>
        ))}
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>复核</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => <td key={column}>{row[column] ?? '—'}</td>)}
              <td><Link className="link" to="/experiment-review">查看复核</Link></td>
              <td className="row-actions">
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 2}>暂无分析实验管理数据，可先登记分析实验</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条分析实验管理记录</span>
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}

