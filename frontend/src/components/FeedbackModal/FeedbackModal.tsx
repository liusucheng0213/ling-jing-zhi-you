import { useState } from 'react'
import { Modal, Rate, TextArea, Toast } from 'antd-mobile'
import { motion } from 'framer-motion'
import './FeedbackModal.css'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

interface Props {
  visible: boolean
  onClose: () => void
  sessionId?: string | null
}

const SATISFACTION_LABELS = ['非常不满意', '不满意', '一般', '满意', '非常满意']
const FEEDBACK_TAGS = ['回答准确', '讲解生动', '态度友好', '响应迅速', '有待改进', '不够详细']
const DIMENSION_LABELS = [
  ['answer_accuracy', '回答准确性'],
  ['guide_vividness', '讲解生动度'],
  ['avatar_voice', '语音/数字人体验'],
  ['route_usefulness', '路线实用性'],
] as const

export default function FeedbackModal({ visible, onClose, sessionId }: Props) {
  const [rating, setRating] = useState(5)
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [comment, setComment] = useState('')
  const [dimensionScores, setDimensionScores] = useState<Record<string, number>>({
    answer_accuracy: 5,
    guide_vividness: 5,
    avatar_voice: 5,
    route_usefulness: 5,
  })
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  const toggleTag = (tag: string) => {
    setSelectedTags(prev =>
      prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag]
    )
  }

  const handleSubmit = async () => {
    if (rating === 0) {
      Toast.show({ content: '请选择满意度评分', icon: 'fail' })
      return
    }
    if (!sessionId) {
      Toast.show({ content: '会话尚未创建，暂不能提交评价', icon: 'fail' })
      return
    }

    setSubmitting(true)
    try {
      const response = await fetch(`${API_BASE}/api/v1/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          rating,
          tags: selectedTags,
          feedback_text: comment.trim() || undefined,
          dimension_scores: dimensionScores,
        }),
      })

      if (!response.ok) throw new Error(`请求失败: ${response.status}`)

      setSubmitted(true)
      Toast.show({ content: '感谢您的评价！', icon: 'success' })
      setTimeout(() => {
        handleClose()
      }, 1500)
    } catch (error) {
      console.error('提交反馈失败:', error)
      Toast.show({ content: '提交失败，请稍后重试', icon: 'fail' })
    } finally {
      setSubmitting(false)
    }
  }

  const handleClose = () => {
    setRating(5)
    setSelectedTags([])
    setComment('')
    setDimensionScores({
      answer_accuracy: 5,
      guide_vividness: 5,
      avatar_voice: 5,
      route_usefulness: 5,
    })
    setSubmitted(false)
    onClose()
  }

  return (
    <Modal
      visible={visible}
      title='✨ 服务评价'
      content={
        <div className='feedback-content'>
          {submitted ? (
            <motion.div
              className='feedback-success'
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
            >
              <div className='success-icon'>🎉</div>
              <p>感谢您的反馈！</p>
              <p className='success-sub'>您的建议将帮助我们做得更好</p>
            </motion.div>
          ) : (
            <>
              {/* 满意度评分 */}
              <div className='feedback-section'>
                <label className='feedback-label'>您对本次服务满意吗？</label>
                <div className='rating-row'>
                  <Rate
                    value={rating}
                    onChange={setRating}
                    style={{ '--star-size': '28px' } as React.CSSProperties}
                  />
                </div>
                <span className='rating-label'>{SATISFACTION_LABELS[rating - 1]}</span>
              </div>

              {/* 标签选择 */}
              <div className='feedback-section'>
                <label className='feedback-label'>分维度体验</label>
                <div className='dimension-list'>
                  {DIMENSION_LABELS.map(([key, label]) => (
                    <div className='dimension-row' key={key}>
                      <span>{label}</span>
                      <Rate
                        value={dimensionScores[key]}
                        onChange={(value) => setDimensionScores(prev => ({ ...prev, [key]: value }))}
                        style={{ '--star-size': '18px' } as React.CSSProperties}
                      />
                    </div>
                  ))}
                </div>
              </div>

              {/* 标签选择 */}
              <div className='feedback-section'>
                <label className='feedback-label'>请选择评价标签（可多选）</label>
                <div className='tag-grid'>
                  {FEEDBACK_TAGS.map(tag => (
                    <span
                      key={tag}
                      className={`feedback-tag ${selectedTags.includes(tag) ? 'selected' : ''}`}
                      onClick={() => toggleTag(tag)}
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>

              {/* 文字评价 */}
              <div className='feedback-section'>
                <label className='feedback-label'>其他建议（可选）</label>
                <TextArea
                  placeholder='请输入您的宝贵建议...'
                  value={comment}
                  onChange={setComment}
                  rows={3}
                  maxLength={200}
                  showCount
                />
              </div>
            </>
          )}
        </div>
      }
      closeOnAction={false}
      onClose={handleClose}
      actions={
        submitted
          ? []
          : [
              { key: 'cancel', text: '暂不评价', onClick: handleClose },
              {
                key: 'submit',
                text: submitting ? '提交中...' : '提交评价',
                onClick: handleSubmit,
              },
            ]
      }
    />
  )
}
