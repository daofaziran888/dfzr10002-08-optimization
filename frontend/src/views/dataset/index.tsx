import { useCallback, useEffect, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/dataset'
const columns = [
  "数据集编号",
  "数据集名称",
  "来源表名",
  "字段列表",
  "行数上限",
  "刷新频率",
  "最近刷新",
  "是否启用"
]
const actions = [
  "提交校验",
  "启用配置",
  "停用配置",
  "刷新数据集"
]

type Row = {
  id: number
  status?: string
  数据集编号: string
  数据集名称: string
  来源表名: string
  字段列表: string
  行数上限: string
  刷新频率: string
  最近刷新: string
  是否启用: string
  最近刷新代次: number
  最近刷新时间: string
  被实验引用: string[]
  引用实验: { 实验编号: string; 实验名称: string; 实验状态: string }[]
}

export default function DatasetView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [message, setMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const filterFields = ["数据集编号", "来源表名"]

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('数据集列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '分析数据集列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    setMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ values: { action } }),
      })
      if (!response.ok) {
        throw new Error('分析数据集动作未生效，请稍后重试')
      }
      const payload = await response.json()
      setMessage(payload.message ?? '')
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '分析数据集操作失败')
    }
  }

  const referenced = rows.filter((row) => (row.被实验引用 ?? []).length > 0).length

  return (
    <section className="page" data-module="dataset">
      <header className="page-head">
        <div>
          <h2>分析数据集管理</h2>
          <p className="page-desc">
            维护分析可用的数据集定义、字段范围与刷新策略；清单按数据集最近刷新代次展示，
            并标出被哪些分析实验引用，与实验复核页使用的新代次保持一致。
          </p>
        </div>
        <div className="page-actions">
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出分析数据集清单
          </button>
        </div>
      </header>

      {errorMessage && <p className="error-text">{errorMessage}</p>}
      {message && <p className="ok-text">{message}</p>}

      <div className="stat-row">
        {[
          { label: '分析数据集总数', value: total },
          { label: '被实验引用', value: referenced },
          { label: '待校验数据集', value: rows.filter((row) => row.status === '待校验').length },
          { label: '已启用数据集', value: rows.filter((row) => row.status === '已启用').length },
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
            <th>最近刷新代次</th>
            <th>最近刷新时间</th>
            <th>被实验引用</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => <td key={column}>{String(row[column as keyof Row] ?? '—')}</td>)}
              <td>
                <span className="badge">代次 {row.最近刷新代次}</span>
              </td>
              <td>{row.最近刷新时间}</td>
              <td>
                {(row.引用实验 ?? []).length === 0 && '—'}
                {(row.引用实验 ?? []).map((experiment) => (
                  <div key={experiment.实验编号}>
                    <span className="badge">{experiment.实验编号}</span>
                    <span className="review-meta">{experiment.实验名称}</span>
                  </div>
                ))}
              </td>
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
              <td className="empty-state" colSpan={columns.length + 4}>暂无分析数据集数据，可先登记数据集</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条分析数据集记录</span>
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
