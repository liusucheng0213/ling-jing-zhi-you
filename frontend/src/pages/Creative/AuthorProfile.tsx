import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button, Card, Tag, Toast } from 'antd-mobile'
import { LeftOutline, LikeOutline, MessageOutline, StarOutline } from 'antd-mobile-icons'
import { api } from '../../api/client'
import { DEFAULT_AVATAR } from '../../stores/user'
import './AuthorProfile.css'

interface CommunityPost {
  id: string
  title: string
  content: string
  nickname: string
  avatar_url: string
  bio: string
  image_urls: string[]
  like_count: number
  comment_count: number
  favorite_count: number
  is_followed: boolean
  visibility: 'public' | 'followers' | 'private'
  follower_count: number
  created_at: string
}

interface AuthorProfileResponse {
  nickname: string
  avatar_url: string
  bio: string
  visibility: 'public' | 'followers' | 'private'
  is_followed: boolean
  follower_count: number
  post_count: number
  posts: CommunityPost[]
}

export default function AuthorProfile() {
  const navigate = useNavigate()
  const { nickname = '' } = useParams()
  const decodedNickname = useMemo(() => decodeURIComponent(nickname || '游客'), [nickname])
  const [profile, setProfile] = useState<AuthorProfileResponse | null>(null)
  const [loading, setLoading] = useState(true)

  const loadProfile = async () => {
    setLoading(true)
    try {
      const data = await api.get<AuthorProfileResponse>(
        `/creative/community/authors/${encodeURIComponent(decodedNickname)}`
      )
      setProfile(data)
    } catch {
      Toast.show({ content: '作者资料加载失败', icon: 'fail' })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadProfile()
  }, [decodedNickname])

  const followAuthor = async () => {
    const firstPost = profile?.posts?.[0]
    if (!firstPost) return
    try {
      const updated = await api.post<CommunityPost>(`/creative/community/posts/${firstPost.id}/follow`)
      setProfile((prev) => prev ? {
        ...prev,
        is_followed: updated.is_followed,
        follower_count: updated.follower_count,
        posts: prev.posts.map((post) => (post.id === updated.id ? updated : post)),
      } : prev)
    } catch {
      Toast.show({ content: '关注失败', icon: 'fail' })
    }
  }

  const formatTime = (value: string) => {
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return '刚刚'
    return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
  }

  return (
    <div className="author-profile-page">
      <div className="author-topbar">
        <button onClick={() => navigate('/creative')} title="返回文创社区">
          <LeftOutline />
        </button>
        <span>作者资料</span>
      </div>

      {loading ? (
        <div className="author-loading">正在加载作者资料...</div>
      ) : (
        <>
          <Card className="author-profile-card">
            <div className="author-hero">
              <img
                src={profile?.avatar_url || DEFAULT_AVATAR}
                alt={profile?.nickname}
                onError={(event) => {
                  event.currentTarget.onerror = null
                  event.currentTarget.src = DEFAULT_AVATAR
                }}
              />
              <div>
                <strong>{profile?.nickname || decodedNickname}</strong>
                <p>{profile?.bio || '这位游客还没有留下自我介绍。'}</p>
                <div className="author-tags">
                  <Tag color={profile?.visibility === 'public' ? 'success' : 'warning'}>
                    {profile?.visibility === 'public' ? '公开资料' : '非公开资料'}
                  </Tag>
                  <Tag>{profile?.post_count || 0} 篇游记</Tag>
                  <Tag>{profile?.follower_count || 0} 人关注</Tag>
                </div>
              </div>
            </div>
            <Button
              block
              color="primary"
              fill={profile?.is_followed ? 'outline' : 'solid'}
              disabled={!profile?.posts?.length}
              onClick={followAuthor}
            >
              {profile?.is_followed ? '已关注' : '关注作者'}
            </Button>
          </Card>

          <section className="author-posts">
            <div className="author-section-title">
              <h2>公开游记</h2>
            </div>
            {(profile?.posts || []).length === 0 ? (
              <div className="author-empty">
                <span className="author-empty-icon">🍃</span>
                <p>暂无可公开展示的游记</p>
                <small>作者发布公开游记后会出现在这里</small>
              </div>
            ) : (
              profile?.posts.map((post) => (
                <article className="author-post-card" key={post.id}>
                  <div className="post-line">
                    <span>{formatTime(post.created_at)}</span>
                    <Tag color="success">公开</Tag>
                  </div>
                  <h3>{post.title}</h3>
                  <p>{post.content}</p>
                  {post.image_urls?.length > 0 && (
                    <div className="author-post-images">
                      {post.image_urls.map((url, index) => (
                        <img key={url} src={url} alt={`${post.title}配图 ${index + 1}`} loading="lazy" />
                      ))}
                    </div>
                  )}
                  <div className="post-stats">
                    <span><LikeOutline /> {post.like_count}</span>
                    <span><MessageOutline /> {post.comment_count}</span>
                    <span><StarOutline /> {post.favorite_count}</span>
                  </div>
                </article>
              ))
            )}
          </section>
        </>
      )}
    </div>
  )
}
