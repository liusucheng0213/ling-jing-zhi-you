import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Card, Selector, Tag, TextArea, Toast } from 'antd-mobile'
import {
  CameraOutline,
  HeartOutline,
  FileOutline,
  LikeOutline,
  MessageOutline,
  PictureOutline,
  RedoOutline,
  SendOutline,
  StarOutline,
  UploadOutline,
} from 'antd-mobile-icons'
import { AnimatePresence, motion } from 'framer-motion'
import { api } from '../../api/client'
import { type ImageJourneyResult, useChatStore } from '../../stores/chat'
import { useJourneyStore } from '../../stores/journey'
import { DEFAULT_AVATAR, useUserStore } from '../../stores/user'
import './Creative.css'

const POEM_STYLES = [
  { label: '古典', value: '古典' },
  { label: '现代', value: '现代' },
]

const POSTCARD_TEMPLATES = [
  { label: '经典', value: 'classic' },
  { label: '可爱', value: 'cute' },
  { label: '极简', value: 'minimal' },
]

const SCENERY_IMAGES: Record<string, string> = {
  buddha: '/assets/scenery/lingshan-scenic.jpg',
  palace: '/assets/scenery/lingshan-palace.jpg',
  scenic: '/assets/scenery/lingshan-buddha.jpg',
  history: '/assets/routes/route-history.webp',
  nature: '/assets/routes/route-nature.webp',
  family: '/assets/routes/route-family.webp',
}

const SPOT_MAP: Record<string, { id: string; icon: string; imageKey: string }> = {
  灵山大佛: { id: 'LS-011', icon: '大', imageKey: 'buddha' },
  梵宫: { id: 'LS-013', icon: '宫', imageKey: 'palace' },
  九龙灌浴: { id: 'LS-006', icon: '泉', imageKey: 'scenic' },
  五印坛城: { id: 'LS-014', icon: '城', imageKey: 'history' },
}

const getApiErrorMessage = (error: unknown, defaultMessage: string) => {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' && detail.trim() ? detail : defaultMessage
}

interface CommunityPost {
  id: string
  title: string
  content: string
  nickname: string
  avatar_url: string
  bio: string
  image_names: string[]
  image_urls: string[]
  like_count: number
  comment_count: number
  favorite_count: number
  is_liked: boolean
  is_favorited: boolean
  is_followed: boolean
  is_hidden: boolean
  visibility: 'public' | 'followers' | 'private'
  report_count: number
  follower_count: number
  comments: CommunityComment[]
  created_at: string
}

interface CommunityComment {
  id: string
  nickname: string
  avatar_url: string
  content: string
  created_at: string
}

interface FeedResponse {
  items: CommunityPost[]
  total: number
}

interface PhotoTip {
  location: string
  angle: string
  time: string
  tip: string
  description: string
  safety?: string
  image_key?: string
  marker_x?: number
  marker_y?: number
  frame_x?: number
  frame_y?: number
  frame_width?: number
  frame_height?: number
}

interface LocalImage {
  name: string
  url: string
  dataUrl: string
  originalDataUrl: string
  file: File
}

interface PostcardItem {
  id: string
  spot: string
  title: string
  content: string
  message: string
  template: string
  imageKey: string
  imageDataUrl?: string
  imageContext?: string
  createdAt: string
}

type ReviewImage = LocalImage

const SHOWCASE_NOISE_TERMS = ['测试', '检查', '回归', '接口']

function isShowcaseNoise(text: string) {
  return SHOWCASE_NOISE_TERMS.some((term) => text.includes(term))
}

const fileToDataUrl = (file: File) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = reject
    reader.readAsDataURL(file)
  })

const loadDataUrlImage = (src: string) =>
  new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = reject
    image.src = src
  })

async function prepareCommunityImage(file: File): Promise<LocalImage> {
  if (!file.type.startsWith('image/')) throw new Error('请选择图片文件')
  if (file.size > 12 * 1024 * 1024) throw new Error('单张原图不能超过 12MB')

  const source = await fileToDataUrl(file)
  const image = await loadDataUrlImage(source)
  const maxDimension = 1600
  const scale = Math.min(1, maxDimension / Math.max(image.naturalWidth, image.naturalHeight))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(image.naturalWidth * scale))
  canvas.height = Math.max(1, Math.round(image.naturalHeight * scale))
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('当前浏览器无法处理图片')
  ctx.fillStyle = '#fff'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height)
  const dataUrl = canvas.toDataURL('image/jpeg', 0.84)
  if (dataUrl.length > 4_000_000) throw new Error('图片压缩后仍过大，请换一张图片')
  return { name: file.name, url: URL.createObjectURL(file), dataUrl, originalDataUrl: source, file }
}

function useDefaultAvatar(event: React.SyntheticEvent<HTMLImageElement>) {
  const image = event.currentTarget
  image.onerror = null
  image.src = DEFAULT_AVATAR
}

export default function Creative() {
  const navigate = useNavigate()
  const userInfo = useUserStore((state) => state.userInfo)
  const sendImageMessage = useChatStore((state) => state.sendImageMessage)
  const playMessageTTS = useChatStore((state) => state.playMessageTTS)
  const selectedAvatar = useChatStore((state) => state.selectedAvatar)
  const activeJourney = useJourneyStore((state) => state.activeJourney)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const reviewFileInputRef = useRef<HTMLInputElement | null>(null)
  const localImagesRef = useRef<LocalImage[]>([])
  const communityComposerRef = useRef<HTMLDivElement | null>(null)

  const [activeSection, setActiveSection] = useState<'ai' | 'community'>('ai')
  const [secondaryToolsOpen, setSecondaryToolsOpen] = useState(false)

  const [feedLoading, setFeedLoading] = useState(false)
  const [polishing, setPolishing] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [reviewLoading, setReviewLoading] = useState(false)
  const [posts, setPosts] = useState<CommunityPost[]>([])
  const [expandedComments, setExpandedComments] = useState<Record<string, boolean>>({})
  const [commentDrafts, setCommentDrafts] = useState<Record<string, string>>({})

  const [draftTitle, setDraftTitle] = useState('')
  const [draftContent, setDraftContent] = useState('')
  const [draftSpots, setDraftSpots] = useState<string[]>([])
  const [localImages, setLocalImages] = useState<LocalImage[]>([])

  const [poem, setPoem] = useState('')
  const [poemTitle, setPoemTitle] = useState('')
  const [poemStyle, setPoemStyle] = useState<string[]>(['古典'])
  const [userFeeling, setUserFeeling] = useState('')

  const [postcards, setPostcards] = useState<PostcardItem[]>([])
  const [postcardTemplate, setPostcardTemplate] = useState<string[]>(['classic'])
  const [postcardMessage, setPostcardMessage] = useState('')
  const [selectedSpot, setSelectedSpot] = useState<string | null>(null)

  const [photoTips, setPhotoTips] = useState<PhotoTip[]>([])
  const [photoSpotName, setPhotoSpotName] = useState('')
  const [reviewImage, setReviewImage] = useState<ReviewImage | null>(null)
  const [reviewSpot, setReviewSpot] = useState<string[]>([])
  const [reviewContext, setReviewContext] = useState('')
  const [reviewResult, setReviewResult] = useState<ImageJourneyResult | null>(null)
  const [reviewNarrated, setReviewNarrated] = useState(false)

  const spotOptions = useMemo(
    () => Object.keys(SPOT_MAP).map((spot) => ({ label: spot, value: spot })),
    []
  )
  const reviewCreativeCompleted = Boolean(
    reviewImage && (
      localImages.some((item) => item.dataUrl === reviewImage.dataUrl)
      || postcards.some((item) => item.imageDataUrl === reviewImage.originalDataUrl)
    )
  )

  useEffect(() => {
    fetchFeed()
  }, [])

  useEffect(() => {
    localImagesRef.current = localImages
  }, [localImages])

  useEffect(() => () => {
    localImagesRef.current.forEach((image) => URL.revokeObjectURL(image.url))
  }, [])

  useEffect(() => {
    return () => {
      if (reviewImage) URL.revokeObjectURL(reviewImage.url)
    }
  }, [reviewImage])

  const fetchFeed = async () => {
    setFeedLoading(true)
    try {
      const data = await api.get<FeedResponse>('/creative/community/feed', { limit: 20 })
      const visiblePosts = data.items
        .filter((post) => !isShowcaseNoise(`${post.title} ${post.content} ${post.nickname}`))
        .map((post) => {
          const comments = (post.comments || []).filter((comment) => (
            !isShowcaseNoise(`${comment.nickname} ${comment.content}`)
          ))
          return { ...post, comments, comment_count: comments.length }
        })
      const featuredIndex = visiblePosts.findIndex((post) => post.comments.length > 0)
      if (featuredIndex > 0) {
        visiblePosts.unshift(visiblePosts.splice(featuredIndex, 1)[0])
      }
      setPosts(visiblePosts)
      const featured = visiblePosts.find((post) => post.comments.length > 0)
      if (featured) {
        setExpandedComments((prev) => ({ ...prev, [featured.id]: true }))
      }
    } catch {
      Toast.show({ content: '社区内容加载失败，请稍后重试', icon: 'fail' })
    } finally {
      setFeedLoading(false)
    }
  }

  const polishJournal = async () => {
    if (!draftContent.trim()) {
      Toast.show({ content: '先写一点游览感受', icon: 'fail' })
      return
    }
    setPolishing(true)
    try {
      const data = await api.post<{ title: string; content: string }>('/creative/journal/polish', {
        title: draftTitle || undefined,
        content: draftContent,
        spots: draftSpots,
      })
      setDraftTitle(data.title)
      setDraftContent(data.content)
      Toast.show({ content: '已润色，可继续编辑', icon: 'success' })
    } catch {
      Toast.show({ content: '润色失败，请稍后重试', icon: 'fail' })
    } finally {
      setPolishing(false)
    }
  }

  const publishPost = async () => {
    if (!draftTitle.trim() || !draftContent.trim()) {
      Toast.show({ content: '标题和正文都要填写', icon: 'fail' })
      return
    }
    setPublishing(true)
    try {
      const post = await api.post<CommunityPost>('/creative/community/posts', {
        title: draftTitle,
        content: draftContent,
        spots: draftSpots,
        image_names: localImages.map((image) => image.name),
        image_data_urls: localImages.map((image) => image.dataUrl),
        nickname: userInfo?.nickname || '游客',
        avatar_url: userInfo?.avatar || DEFAULT_AVATAR,
        bio: userInfo?.bio || '',
        visibility: userInfo?.visibility || 'public',
      })
      setPosts((prev) => [post, ...prev])
      setDraftTitle('')
      setDraftContent('')
      setDraftSpots([])
      localImages.forEach((image) => URL.revokeObjectURL(image.url))
      setLocalImages([])
      Toast.show({ content: '游记已发布到社区', icon: 'success' })
    } catch (error) {
      Toast.show({ content: getApiErrorMessage(error, '发布失败，请稍后重试'), icon: 'fail' })
    } finally {
      setPublishing(false)
    }
  }

  const likePost = async (postId: string) => {
    try {
      const updated = await api.post<CommunityPost>(`/creative/community/posts/${postId}/like`)
      setPosts((prev) => prev.map((post) => (post.id === postId ? updated : post)))
    } catch {
      Toast.show({ content: '点赞失败', icon: 'fail' })
    }
  }

  const favoritePost = async (postId: string) => {
    try {
      const updated = await api.post<CommunityPost>(`/creative/community/posts/${postId}/favorite`)
      setPosts((prev) => prev.map((post) => (post.id === postId ? updated : post)))
    } catch {
      Toast.show({ content: '收藏失败', icon: 'fail' })
    }
  }

  const followAuthor = async (postId: string) => {
    try {
      const updated = await api.post<CommunityPost>(`/creative/community/posts/${postId}/follow`)
      setPosts((prev) => prev.map((post) => (post.id === postId ? updated : post)))
    } catch {
      Toast.show({ content: '关注失败', icon: 'fail' })
    }
  }

  const reportPost = async (postId: string) => {
    const reason = window.prompt('请输入举报原因（例如：内容不适、广告、侵犯隐私）')
    if (!reason?.trim()) return
    try {
      const updated = await api.post<CommunityPost>(`/creative/community/posts/${postId}/report`, {
        reason: reason.trim(),
        nickname: userInfo?.nickname || '游客',
      })
      setPosts((prev) => prev.map((post) => (post.id === postId ? updated : post)))
      Toast.show({ content: '举报已提交', icon: 'success' })
    } catch {
      Toast.show({ content: '举报失败', icon: 'fail' })
    }
  }

  const submitComment = async (postId: string) => {
    const content = (commentDrafts[postId] || '').trim()
    if (!content) {
      Toast.show({ content: '先写一句评论', icon: 'fail' })
      return
    }
    try {
      const updated = await api.post<CommunityPost>(`/creative/community/posts/${postId}/comments`, {
        content,
        nickname: userInfo?.nickname || '游客',
        avatar_url: userInfo?.avatar || DEFAULT_AVATAR,
      })
      setPosts((prev) => prev.map((post) => (post.id === postId ? updated : post)))
      setCommentDrafts((prev) => ({ ...prev, [postId]: '' }))
      setExpandedComments((prev) => ({ ...prev, [postId]: true }))
      Toast.show({ content: '评论已发布', icon: 'success' })
    } catch {
      Toast.show({ content: '评论失败', icon: 'fail' })
    }
  }

  const handleImageChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []).slice(0, 3)
    event.target.value = ''
    if (!files.length) return
    try {
      const prepared = await Promise.all(files.map(prepareCommunityImage))
      localImages.forEach((image) => URL.revokeObjectURL(image.url))
      setLocalImages(prepared)
      Toast.show({ content: `已准备 ${prepared.length} 张图片，发布时会一并上传`, icon: 'success' })
    } catch (error) {
      Toast.show({ content: error instanceof Error ? error.message : '图片处理失败', icon: 'fail' })
    }
  }

  const handleReviewImageChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (!file.type.startsWith('image/')) {
      Toast.show({ content: '请选择图片文件', icon: 'fail' })
      return
    }
    try {
      const prepared = await prepareCommunityImage(file)
      if (reviewImage) URL.revokeObjectURL(reviewImage.url)
      setReviewImage(prepared)
      setReviewResult(null)
      setReviewNarrated(false)
    } catch (error) {
      Toast.show({ content: error instanceof Error ? error.message : '读取照片失败', icon: 'fail' })
    }
  }

  const analyzeReviewImage = async () => {
    if (!reviewImage) {
      Toast.show({ content: '先选择一张照片', icon: 'fail' })
      return
    }
    setReviewLoading(true)
    try {
      const chosenSpot = reviewSpot[0]
      const result = await sendImageMessage(
        reviewImage.file,
        reviewContext || '请识别画面，核对景点知识，并给出适合游记和明信片的建议。',
        chosenSpot ? SPOT_MAP[chosenSpot]?.id : activeJourney?.currentSpot?.id,
        selectedAvatar,
        activeJourney?.routeId,
        { creativeMode: true, narrate: false },
      )
      setReviewResult(result)
      setReviewNarrated(false)
      Toast.show({
        content: '识景、知识核对与文创建议已完成',
        icon: 'success',
      })
    } catch (error) {
      Toast.show({ content: getApiErrorMessage(error, '照片点评请求失败'), icon: 'fail' })
    } finally {
      setReviewLoading(false)
    }
  }

  const narrateReview = () => {
    if (!reviewResult?.answer) return
    playMessageTTS(reviewResult.answer, selectedAvatar)
    setReviewNarrated(true)
    Toast.show({ content: '数字人正在复用本次识景结果讲解', icon: 'success' })
  }

  const writeReviewAsJournal = () => {
    if (!reviewResult || !reviewImage) return
    const spotName = reviewResult.recognizedSpots[0] || reviewSpot[0] || '灵山胜境'
    const paragraphs = [
      reviewResult.sceneDescription,
      reviewResult.answer,
      reviewResult.publishTip,
    ].filter((item): item is string => Boolean(item?.trim()))
    setDraftTitle(`镜头里的${spotName}`)
    setDraftContent(paragraphs.join('\n\n'))
    setDraftSpots(reviewResult.recognizedSpots.length ? reviewResult.recognizedSpots : reviewSpot)
    setLocalImages((current) => {
      if (current.some((item) => item.dataUrl === reviewImage.dataUrl)) return current
      const attached = {
        ...reviewImage,
        url: URL.createObjectURL(reviewImage.file),
      }
      const next = [attached, ...current]
      next.slice(3).forEach((item) => URL.revokeObjectURL(item.url))
      return next.slice(0, 3)
    })
    setActiveSection('community')
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
      communityComposerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      communityComposerRef.current?.focus({ preventScroll: true })
    }))
    Toast.show({ content: '已把识景结果和同一张照片带入游记编辑器', icon: 'success' })
  }

  const buildReviewImageContext = () => {
    if (!reviewResult) return undefined
    return [
      reviewResult.sceneDescription && `画面：${reviewResult.sceneDescription}`,
      reviewResult.visualFacts.length && `可见事实：${reviewResult.visualFacts.join('；')}`,
      reviewResult.recognizedSpots.length && `已确认景点：${reviewResult.recognizedSpots.join('、')}`,
      reviewResult.publishTip && `发布建议：${reviewResult.publishTip}`,
    ].filter(Boolean).join('\n')
  }

  const generatePoem = async () => {
    setGenerating(true)
    try {
      const data = await api.post<any>('/creative/poem', {
        spot_id: 'LS-011',
        theme: '禅意',
        style: poemStyle[0] || '古典',
        user_input: userFeeling || undefined,
      })
      setPoemTitle(data.title || '')
      setPoem(data.content || '')
      Toast.show({ content: '纪念诗词已生成', icon: 'success' })
    } catch (error) {
      Toast.show({ content: getApiErrorMessage(error, '生成失败，请稍后重试'), icon: 'fail' })
    } finally {
      setGenerating(false)
    }
  }

  const generatePostcard = async (
    spotName: string,
    imageOptions?: { imageDataUrl?: string; imageContext?: string },
  ) => {
    const spotInfo = SPOT_MAP[spotName]
    if (!spotInfo) return
    setSelectedSpot(spotName)
    setGenerating(true)
    try {
      const data = await api.post<any>('/creative/postcard', {
        spot_id: spotInfo.id,
        template: postcardTemplate[0] || 'classic',
        message: postcardMessage || undefined,
        include_photo: false,
        image_context: imageOptions?.imageContext,
      })
      setPostcards((prev) => [
        {
          id: data.id,
          spot: spotName,
          title: data.title,
          content: data.content,
          message: data.content || postcardMessage,
          template: postcardTemplate[0] || 'classic',
          imageKey: spotInfo.imageKey,
          imageDataUrl: imageOptions?.imageDataUrl,
          imageContext: imageOptions?.imageContext,
          createdAt: new Date().toISOString(),
        },
        ...prev,
      ])
      Toast.show({ content: `${spotName}明信片已生成`, icon: 'success' })
    } catch (error) {
      Toast.show({ content: getApiErrorMessage(error, '生成失败，请稍后重试'), icon: 'fail' })
    } finally {
      setGenerating(false)
      setSelectedSpot(null)
    }
  }

  const generateReviewPostcard = () => {
    if (!reviewResult || !reviewImage) return
    const spotName = [reviewResult.recognizedSpots[0], reviewSpot[0]]
      .find((item): item is string => Boolean(item && SPOT_MAP[item]))
    if (!spotName) {
      Toast.show({ content: '请先从上方选择一个已确认景点，再生成照片明信片', icon: 'fail' })
      return
    }
    setSecondaryToolsOpen(true)
    void generatePostcard(spotName, {
      imageDataUrl: reviewImage.originalDataUrl,
      imageContext: buildReviewImageContext(),
    })
  }

  const getPhotoTips = async (spotName: string) => {
    const spotInfo = SPOT_MAP[spotName]
    if (!spotInfo) return
    setPhotoSpotName(spotName)
    try {
      const data = await api.get<{ tips: PhotoTip[] }>(`/creative/photo-tips/${spotInfo.id}`)
      setPhotoTips(data.tips || [])
    } catch {
      Toast.show({ content: '获取拍照推荐失败', icon: 'fail' })
    }
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text).then(() => {
      Toast.show({ content: '已复制到剪贴板', icon: 'success' })
    })
  }

  const formatTime = (value: string) => {
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return '刚刚'
    return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
  }

  const getSceneryImage = (imageKey?: string) => SCENERY_IMAGES[imageKey || ''] || SCENERY_IMAGES.scenic

  const getTemplateLabel = (template: string) =>
    POSTCARD_TEMPLATES.find((item) => item.value === template)?.label || '经典'

  const drawCoverImage = (
    ctx: CanvasRenderingContext2D,
    image: HTMLImageElement,
    x: number,
    y: number,
    width: number,
    height: number
  ) => {
    const scale = Math.max(width / image.width, height / image.height)
    const drawWidth = image.width * scale
    const drawHeight = image.height * scale
    ctx.save()
    ctx.beginPath()
    ctx.rect(x, y, width, height)
    ctx.clip()
    ctx.drawImage(image, x + (width - drawWidth) / 2, y + (height - drawHeight) / 2, drawWidth, drawHeight)
    ctx.restore()
  }

  const wrapCanvasText = (
    ctx: CanvasRenderingContext2D,
    text: string,
    x: number,
    y: number,
    maxWidth: number,
    lineHeight: number,
    maxLines: number
  ) => {
    const source = text.trim()
    let line = ''
    let lineCount = 0
    for (const char of source) {
      const nextLine = line + char
      if (ctx.measureText(nextLine).width > maxWidth && line) {
        ctx.fillText(line, x, y + lineCount * lineHeight)
        line = char
        lineCount += 1
        if (lineCount >= maxLines) return
      } else {
        line = nextLine
      }
    }
    if (line && lineCount < maxLines) {
      ctx.fillText(line, x, y + lineCount * lineHeight)
    }
  }

  const downloadPostcard = async (postcard: PostcardItem) => {
    try {
      const canvas = document.createElement('canvas')
      canvas.width = 1200
      canvas.height = 800
      const ctx = canvas.getContext('2d')
      if (!ctx) throw new Error('Canvas not supported')

      const [image, paper] = await Promise.all([
        loadDataUrlImage(postcard.imageDataUrl || getSceneryImage(postcard.imageKey)),
        loadDataUrlImage('/assets/creative/postcard-paper-v1.webp'),
      ])
      const photoWidth = 660
      const copyX = photoWidth
      const copyWidth = canvas.width - photoWidth
      drawCoverImage(ctx, image, 0, 0, photoWidth, canvas.height)

      const photoShade = ctx.createLinearGradient(0, 0, photoWidth, canvas.height)
      photoShade.addColorStop(0, 'rgba(13, 26, 52, 0.04)')
      photoShade.addColorStop(1, 'rgba(13, 26, 52, 0.42)')
      ctx.fillStyle = photoShade
      ctx.fillRect(0, 0, photoWidth, canvas.height)

      ctx.fillStyle = '#f7f1e4'
      ctx.fillRect(copyX, 0, copyWidth, canvas.height)
      ctx.save()
      ctx.globalAlpha = postcard.template === 'minimal' ? 0.42 : 0.78
      drawCoverImage(ctx, paper, copyX, 0, copyWidth, canvas.height)
      ctx.restore()

      const accent = postcard.template === 'cute' ? '#b96d55' : postcard.template === 'minimal' ? '#40506b' : '#947326'
      ctx.fillStyle = accent
      ctx.fillRect(copyX, 0, 8, canvas.height)

      ctx.fillStyle = 'rgba(255,255,255,0.9)'
      ctx.fillRect(44, 48, 190, 52)
      ctx.fillStyle = '#1e4367'
      ctx.font = '700 27px "Microsoft YaHei", sans-serif'
      ctx.fillText(postcard.spot, 66, 83)

      const textX = copyX + 64
      const textWidth = copyWidth - 128
      ctx.fillStyle = accent
      ctx.font = '600 24px "Microsoft YaHei", sans-serif'
      ctx.fillText(`${getTemplateLabel(postcard.template)} · TRAVEL NOTE`, textX, 96)
      ctx.fillRect(textX, 122, 68, 3)

      ctx.fillStyle = '#1F2A44'
      ctx.font = '700 39px "Microsoft YaHei", sans-serif'
      wrapCanvasText(ctx, postcard.title, textX, 198, textWidth, 52, 2)

      ctx.fillStyle = '#4f5566'
      ctx.font = '28px "Microsoft YaHei", sans-serif'
      wrapCanvasText(ctx, postcard.message || postcard.content, textX, 342, textWidth, 46, 7)

      ctx.fillStyle = accent
      ctx.font = '600 24px "Microsoft YaHei", sans-serif'
      ctx.fillText('灵境智游', textX, 704)
      ctx.fillStyle = '#7a8090'
      ctx.font = '22px "Microsoft YaHei", sans-serif'
      ctx.fillText(new Date(postcard.createdAt).toLocaleDateString('zh-CN'), textX, 744)

      const link = document.createElement('a')
      link.download = `灵境智游-${postcard.spot}-明信片.png`
      link.href = canvas.toDataURL('image/png')
      link.click()
      Toast.show({ content: '明信片已保存', icon: 'success' })
    } catch {
      Toast.show({ content: '保存失败，请稍后重试', icon: 'fail' })
    }
  }

  return (
    <div className="creative-page">
      <div className="creative-header">
        <h1>灵境文创工坊</h1>
      </div>

      <div className="creative-section-tabs" role="tablist" aria-label="文创内容分段">
        <button
          type="button"
          role="tab"
          aria-selected={activeSection === 'ai'}
          aria-controls="creative-ai-panel"
          className={activeSection === 'ai' ? 'is-active' : ''}
          onClick={() => setActiveSection('ai')}
        >
          <PictureOutline /> AI 文创
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeSection === 'community'}
          aria-controls="creative-community-panel"
          className={activeSection === 'community' ? 'is-active' : ''}
          onClick={() => setActiveSection('community')}
        >
          <MessageOutline /> 游记社区
        </button>
      </div>

      <section
        id="creative-community-panel"
        className="creative-section-panel"
        role="tabpanel"
        hidden={activeSection !== 'community'}
        aria-label="游记社区"
      >
      <div ref={communityComposerRef} tabIndex={-1} className="community-composer-focus">

      <Card className="community-composer">
        <div className="composer-head">
          <img
            src={userInfo?.avatar || DEFAULT_AVATAR}
            alt={userInfo?.nickname || '游客'}
            onError={useDefaultAvatar}
          />
          <div>
            <strong>{userInfo?.nickname || '游客'}</strong>
          </div>
        </div>

        <div className="composer-form">
          <input
            className="title-input"
            value={draftTitle}
            onChange={(event) => setDraftTitle(event.target.value)}
            maxLength={80}
            placeholder="给这篇游记起个标题"
          />
          <TextArea
            placeholder="比如：今天在梵宫看见光落在穹顶上，很安静，也很震撼..."
            value={draftContent}
            onChange={setDraftContent}
            rows={4}
            maxLength={1200}
            showCount
          />
          <Selector
            options={spotOptions}
            value={draftSpots}
            onChange={setDraftSpots}
            multiple
            showCheckMark={false}
          />
        </div>

        {localImages.length > 0 && (
          <div className="local-image-list">
            {localImages.map((image) => (
              <div key={image.url} className="local-image">
                <img src={image.url} alt={image.name} />
                <span>{image.name}</span>
              </div>
            ))}
          </div>
        )}

        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          multiple
          hidden
          onChange={handleImageChange}
        />
        <div className="composer-actions">
          <Button fill="outline" onClick={() => fileInputRef.current?.click()}>
            <UploadOutline /> 选择图片
          </Button>
          <Button fill="outline" loading={polishing} onClick={polishJournal}>
            <PictureOutline /> AI润色
          </Button>
          <Button color="primary" loading={publishing} onClick={publishPost}>
            <SendOutline /> 发布
          </Button>
        </div>
      </Card>
      </div>

      <section className="community-feed">
        <div className="section-head">
          <h2>社区新鲜事</h2>
          <button onClick={fetchFeed}>刷新</button>
        </div>
        {feedLoading && <div className="feed-loading">正在加载社区内容...</div>}
        {!feedLoading && posts.length === 0 && (
          <div className="empty-feed">
            <span className="empty-feed-icon">🖋️</span>
            <p>还没有游记</p>
            <small>写下第一篇游记，和大家分享你的灵境之旅吧</small>
          </div>
        )}
        <AnimatePresence>
          {posts.map((post) => (
            <motion.article
              key={post.id}
              className="feed-card"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
            >
              <div className="feed-author">
                <button
                  className="author-link"
                  onClick={() => navigate(`/creative/authors/${encodeURIComponent(post.nickname)}`)}
                  title="查看作者资料"
                >
                  <img src={post.avatar_url || DEFAULT_AVATAR} alt={post.nickname} onError={useDefaultAvatar} />
                </button>
                <button
                  className="author-name"
                  onClick={() => navigate(`/creative/authors/${encodeURIComponent(post.nickname)}`)}
                >
                  <strong>{post.nickname}</strong>
                  <span>{formatTime(post.created_at)} · {post.follower_count || 0} 人关注</span>
                </button>
                <button className={`follow-btn ${post.is_followed ? 'active' : ''}`} onClick={() => followAuthor(post.id)}>
                  {post.is_followed ? '已关注' : '关注'}
                </button>
              </div>
              <h3>{post.title}</h3>
              <div className="feed-meta-tags">
                <Tag color={post.visibility === 'public' ? 'success' : post.visibility === 'followers' ? 'primary' : 'warning'}>
                  {post.visibility === 'public' ? '公开' : post.visibility === 'followers' ? '仅关注可见' : '仅自己可见'}
                </Tag>
                {post.report_count > 0 && <Tag color="danger">已举报 {post.report_count}</Tag>}
              </div>
              <p>{post.content}</p>
              {post.image_urls.length > 0 && (
                <div className={`feed-image-grid count-${Math.min(post.image_urls.length, 3)}`}>
                  {post.image_urls.map((url, index) => (
                    <img key={url} src={url} alt={`${post.title}配图 ${index + 1}`} loading="lazy" />
                  ))}
                </div>
              )}
              {post.image_urls.length === 0 && post.image_names.length > 0 && (
                <div className="image-name-list">
                  {post.image_names.map((name) => (
                    <span key={name}>{name}</span>
                  ))}
                </div>
              )}
              <div className="feed-actions">
                <button className={post.is_liked ? 'active' : ''} onClick={() => likePost(post.id)}>
                  <LikeOutline /> {post.like_count}
                </button>
                <button
                  className={expandedComments[post.id] ? 'active' : ''}
                  onClick={() => setExpandedComments((prev) => ({ ...prev, [post.id]: !prev[post.id] }))}
                >
                  <MessageOutline /> {post.comment_count}
                </button>
                <button className={post.is_favorited ? 'active' : ''} onClick={() => favoritePost(post.id)}>
                  <StarOutline /> {post.favorite_count}
                </button>
              </div>
              <button className="report-btn" onClick={() => reportPost(post.id)}>举报内容</button>
              {expandedComments[post.id] && (
                <div className="comment-panel">
                  <div className="comment-list">
                    {(post.comments || []).length > 0 ? (
                      post.comments.map((comment) => (
                        <div className="comment-item" key={comment.id}>
                          <img src={comment.avatar_url || DEFAULT_AVATAR} alt={comment.nickname} onError={useDefaultAvatar} />
                          <div>
                            <strong>{comment.nickname}</strong>
                            <p>{comment.content}</p>
                          </div>
                        </div>
                      ))
                    ) : (
                      <p className="comment-empty">💬 还没有评论，来写第一句吧。</p>
                    )}
                  </div>
                  <div className="comment-compose">
                    <input
                      value={commentDrafts[post.id] || ''}
                      maxLength={160}
                      placeholder="写一句友好的评论"
                      onChange={(event) => setCommentDrafts((prev) => ({ ...prev, [post.id]: event.target.value }))}
                    />
                    <button onClick={() => submitComment(post.id)}>发送</button>
                  </div>
                </div>
              )}
            </motion.article>
          ))}
        </AnimatePresence>
      </section>

      </section>

      <section
        id="creative-ai-panel"
        className="creative-tools creative-section-panel"
        role="tabpanel"
        hidden={activeSection !== 'ai'}
        aria-label="AI 文创"
      >
        <Card className="creative-card photo-review-card">
          <div className="creative-card-heading">
            <div>
              <h3><PictureOutline /> 照片识景与文创</h3>
            </div>
          </div>
          <div className="image-journey-steps">
            {[
              ['1', '识别画面', Boolean(reviewImage)],
              ['2', '核对知识', Boolean(reviewResult)],
              ['3', '数字人讲解', reviewNarrated],
              ['4', '生成文创', reviewCreativeCompleted],
            ].map(([index, label, done]) => (
              <div className={`image-journey-step ${done ? 'is-done' : ''}`} key={String(index)}>
                <span>{done ? '✓' : index}</span>
                <strong>{label}</strong>
              </div>
            ))}
          </div>
          <input
            ref={reviewFileInputRef}
            type="file"
            accept="image/*"
            hidden
            onChange={handleReviewImageChange}
          />
          <div className="photo-review-layout">
            <button className="review-upload" onClick={() => reviewFileInputRef.current?.click()}>
              {reviewImage ? (
                <img src={reviewImage.url} alt={reviewImage.name} />
              ) : (
                <span><UploadOutline /> 选择一张照片</span>
              )}
            </button>
            <div className="review-form">
              <Selector
                options={spotOptions}
                value={reviewSpot}
                onChange={(value) => setReviewSpot(value.slice(0, 1))}
                showCheckMark={false}
              />
              <TextArea
                placeholder="可补充关注点，例如：想突出建筑层次和文化氛围"
                value={reviewContext}
                onChange={setReviewContext}
                rows={2}
                maxLength={160}
                showCount
              />
              <Button block color="primary" loading={reviewLoading} onClick={analyzeReviewImage}>
                一次完成识景与文创建议
              </Button>
            </div>
          </div>
          {reviewImage && <p className="review-boundary">照片仅用于本次点评，不会公开。</p>}
          {reviewResult && (
            <div className="review-result review-success">
              <p>{reviewResult.answer}</p>
              {typeof reviewResult.confidence === 'number' && (
                <div className="review-confidence">
                  <span>景点/场景判断置信度</span>
                  <strong>{Math.round(reviewResult.confidence * 100)}%</strong>
                </div>
              )}
              {reviewResult.sceneDescription && (
                <div className="review-block">
                  <strong>画面描述</strong>
                  <span>{reviewResult.sceneDescription}</span>
                </div>
              )}
              {reviewResult.visualFacts.length > 0 && (
                <div className="review-block">
                  <strong>画面识别</strong>
                  <ul>
                    {reviewResult.visualFacts.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
              )}
              {reviewResult.recognizedSpots.length > 0 && (
                <div className="review-block">
                  <strong>景点核对</strong>
                  <div className="review-tags">
                    {reviewResult.recognizedSpots.map((item) => <Tag color="primary" key={item}>{item}</Tag>)}
                    <Tag color="success">命中 {reviewResult.knowledgeSourceCount} 条知识</Tag>
                  </div>
                </div>
              )}
              {reviewResult.compositionSuggestions.length > 0 && (
                <div className="review-block">
                  <strong>构图建议</strong>
                  <ul>
                    {reviewResult.compositionSuggestions.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
              )}
              {reviewResult.safetyTips.length > 0 && (
                <div className="review-block">
                  <strong>安全提醒</strong>
                  <ul>
                    {reviewResult.safetyTips.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
              )}
              {reviewResult.publishTip && (
                <div className="review-block">
                  <strong>发布建议</strong>
                  <span>{reviewResult.publishTip}</span>
                </div>
              )}
              <div className="image-journey-actions">
                <Button size="small" color="primary" onClick={narrateReview}>
                  {reviewNarrated ? '再次让数字人讲解' : '让数字人讲解'}
                </Button>
                <Button size="small" fill="outline" onClick={writeReviewAsJournal}>写成游记</Button>
                <Button size="small" fill="outline" loading={generating} onClick={generateReviewPostcard}>
                  生成照片明信片
                </Button>
              </div>
            </div>
          )}
        </Card>

        <div className="creative-secondary-shell">
          <button
            type="button"
            className="creative-secondary-toggle"
            aria-expanded={secondaryToolsOpen}
            aria-controls="creative-secondary-tools"
            onClick={() => setSecondaryToolsOpen((value) => !value)}
          >
            <span>
              <strong>更多文创工具</strong>
            </span>
            <span aria-hidden="true">{secondaryToolsOpen ? '收起' : '展开'}</span>
          </button>
          <div id="creative-secondary-tools" className="creative-secondary-tools" hidden={!secondaryToolsOpen}>

        <Card className="creative-card">
          <h3><CameraOutline /> 智能拍照推荐</h3>
          <div className="photo-spots">
            {Object.keys(SPOT_MAP).map((spot) => (
              <motion.button
                key={spot}
                className={`photo-spot-btn ${photoSpotName === spot ? 'active' : ''}`}
                whileTap={{ scale: 0.95 }}
                onClick={() => getPhotoTips(spot)}
              >
                <span className="spot-icon">{SPOT_MAP[spot].icon}</span>
                <span>{spot}</span>
              </motion.button>
            ))}
          </div>
          <AnimatePresence>
            {photoTips.length > 0 && (
              <motion.div
                className="photo-tips-list"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
              >
                {photoTips.map((tip, idx) => (
                  <div key={idx} className="photo-tip-card">
                    <div
                      className={`photo-guide-visual photo-guide-${tip.image_key || 'scenic'}`}
                      style={{ backgroundImage: `url(${getSceneryImage(tip.image_key)})` }}
                    >
                      <img className="photo-guide-image" src={getSceneryImage(tip.image_key)} alt="构图示意" />
                      <div
                        className="photo-marker"
                        style={{ left: `${tip.marker_x ?? 50}%`, top: `${tip.marker_y ?? 76}%` }}
                      >
                        <span />
                      </div>
                      <div
                        className="photo-marker-label"
                        style={{ left: `${tip.marker_x ?? 50}%`, top: `${tip.marker_y ?? 76}%` }}
                      >
                        建议站位
                      </div>
                      <span className="photo-guide-note">构图示意</span>
                    </div>
                    <div className="tip-header">
                      <Tag color="primary">推荐点 {idx + 1}</Tag>
                      <span className="tip-location">{tip.location}</span>
                    </div>
                    <p className="tip-desc">{tip.description}</p>
                    <div className="tip-details">
                      <div className="tip-item">
                        <span className="tip-label">角度</span>
                        <span className="tip-value">{tip.angle}</span>
                      </div>
                      <div className="tip-item">
                        <span className="tip-label">时间</span>
                        <span className="tip-value">{tip.time}</span>
                      </div>
                      <div className="tip-item">
                        <span className="tip-label">技巧</span>
                        <span className="tip-value">{tip.tip}</span>
                      </div>
                      {tip.safety && (
                        <div className="tip-item tip-safety">
                          <span className="tip-label">现场</span>
                          <span className="tip-value">{tip.safety}</span>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </Card>

        <Card className="creative-card">
          <h3><HeartOutline /> 纪念诗词</h3>
          {poem ? (
            <motion.div className="poem-display" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              {poemTitle && <h4 className="poem-title">{poemTitle}</h4>}
              <pre className="poem-text">{poem}</pre>
              <div className="tool-actions">
                <Button size="small" color="primary" onClick={() => copyToClipboard(poem)}>复制</Button>
                <Button size="small" fill="outline" onClick={() => { setPoem(''); setPoemTitle('') }}>重写</Button>
              </div>
            </motion.div>
          ) : (
            <div className="tool-form">
              <Selector options={POEM_STYLES} value={poemStyle} onChange={setPoemStyle} showCheckMark={false} />
              <TextArea
                placeholder="写下你的游览感悟，AI 将据此创作..."
                value={userFeeling}
                onChange={setUserFeeling}
                rows={3}
                maxLength={200}
                showCount
              />
              <Button block loading={generating} onClick={generatePoem} color="primary" fill="outline">
                生成纪念诗
              </Button>
            </div>
          )}
        </Card>

        <Card className="creative-card">
          <h3><PictureOutline /> 个性化明信片</h3>
          <div className="tool-form">
            <Selector options={POSTCARD_TEMPLATES} value={postcardTemplate} onChange={setPostcardTemplate} showCheckMark={false} />
            <TextArea
              placeholder="写下你想对朋友说的话..."
              value={postcardMessage}
              onChange={setPostcardMessage}
              rows={2}
              maxLength={100}
              showCount
            />
          </div>
          <div className="postcard-grid">
            {reviewImage && reviewResult && (
              <motion.button
                type="button"
                className="postcard-thumb postcard-photo-thumb"
                whileTap={{ scale: 0.95 }}
                onClick={generateReviewPostcard}
                disabled={generating}
              >
                <img className="postcard-img" src={reviewImage.url} alt="本次上传照片" />
                <span>用本次照片</span>
                <Tag color="primary">原图</Tag>
              </motion.button>
            )}
            {Object.keys(SPOT_MAP).map((spot) => (
              <motion.button
                key={spot}
                type="button"
                className="postcard-thumb"
                whileTap={{ scale: 0.95 }}
                onClick={() => generatePostcard(spot)}
                disabled={generating}
              >
                <img className="postcard-img" src={getSceneryImage(SPOT_MAP[spot].imageKey)} alt="" />
                <span>{spot}</span>
                <Tag color="warning">{generating && selectedSpot === spot ? '生成中' : '生成'}</Tag>
              </motion.button>
            ))}
          </div>
          {postcards.length > 0 && (
            <div className="postcard-list">
              {postcards.map((pc) => (
                <motion.div
                  key={pc.id}
                  className={`postcard-item postcard-${pc.template}`}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                >
                  <div className="postcard-preview">
                    <div
                      className="postcard-preview-photo"
                      style={{ backgroundImage: `url(${pc.imageDataUrl || getSceneryImage(pc.imageKey)})` }}
                    >
                      <span>{pc.spot}</span>
                    </div>
                    <div className="postcard-preview-panel">
                      <span className="postcard-style-label">{getTemplateLabel(pc.template)} · TRAVEL NOTE</span>
                      <h5>{pc.title}</h5>
                      <p>{pc.message || pc.content}</p>
                      <span className="postcard-signature">灵境智游 · {formatTime(pc.createdAt)}</span>
                    </div>
                  </div>
                  <div className="postcard-actions">
                    <Button
                      size="small"
                      fill="outline"
                      onClick={() => generatePostcard(pc.spot, {
                        imageDataUrl: pc.imageDataUrl,
                        imageContext: pc.imageContext,
                      })}
                    >
                      <RedoOutline /> 重新生成
                    </Button>
                    <Button size="small" color="primary" onClick={() => downloadPostcard(pc)}>
                      <FileOutline /> 保存图片
                    </Button>
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </Card>
          </div>
        </div>
      </section>
    </div>
  )
}
