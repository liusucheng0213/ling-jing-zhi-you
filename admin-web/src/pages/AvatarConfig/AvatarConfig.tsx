import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Collapse,
  Divider,
  Form,
  Input,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Switch,
  Tag,
  Tooltip,
  message,
} from 'antd'
import {
  ApiOutlined,
  AudioOutlined,
  CheckCircleOutlined,
  EditOutlined,
  EnvironmentOutlined,
  EyeOutlined,
  RobotOutlined,
  ReloadOutlined,
  SmileOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { api, getApiErrorMessage } from '../../api/client'
import { useAvatarChannelStatus } from '../../hooks/useAvatarChannelStatus'
import AvatarLivePreview, { type AvatarPreviewPayload } from './AvatarLivePreview'
import './AvatarConfig.css'

type Gender = 'male' | 'female'
type ProviderType = 'xunfei'

interface AvatarConfig {
  id: number | string
  code: string
  name: string
  title: string
  description: string
  voice: string
  vcn: string
  emotion: string
  triggerSpots: string[]
  enabled: boolean
  gender: Gender
  avatarId: string
  scene: string
  provider: ProviderType
  /** 演示体验完整度（%），由 computeCompleteness 按真实配置计算，不再人工填写 */
  quality?: number
  actionPresets: string[]
  imageUrl?: string
  bundleName?: string
  costumeDescription?: string
  previewVerifiedAt?: string
  previewAvatarId?: string
  previewVoiceId?: string
}

interface AvatarHealth {
  ok: boolean
  checks: Array<{ name: string; ok: boolean; detail: string }>
}

/**
 * 演示体验完整度：按数字人关键配置是否真实齐全计算，全配齐即为 100%。
 * 检查项：基础档案、数字人形象ID、语音音色、动作编排、启用状态。
 */
const computeCompleteness = (avatar: AvatarConfig): number => {
  const checks = [
    Boolean(avatar.name && avatar.title && avatar.description),
    /^\d{9}$/.test(normalizeAvatarId(avatar.avatarId)),
    Boolean(avatar.vcn),
    avatar.actionPresets.length >= 2,
    avatar.enabled,
  ]
  const passed = checks.filter(Boolean).length
  return Math.round((passed / checks.length) * 100)
}

const voiceOptions: Array<{ value: string; label: string; gender: Gender; language: string; description: string }> = [
  { value: 'x4_yezi', label: '小露', gender: 'female', language: '普通话/英语', description: '女声，普通话与英语混合服务场景' },
  { value: 'x4_lingxiaoqi_oral', label: '聆小琪', gender: 'female', language: '普通话', description: '女声，亲切自然的游客问答' },
  { value: 'x4_yiting', label: '小娟-温情', gender: 'female', language: '普通话', description: '女声，温情舒缓讲解' },
  { value: 'x4_yuexiaoni_assist', label: '悦小妮', gender: 'female', language: '普通话', description: '女声，助理型服务提示' },
  { value: 'x4_lingxiaoyu_assist', label: '聆小瑜', gender: 'female', language: '普通话', description: '女声，助理型游客服务' },
  { value: 'x4_lingxiaoying_assist', label: '聆小璎-助理', gender: 'female', language: '普通话', description: '女声，新版助理音色' },
  { value: 'x4_xiaozhong', label: '小钟', gender: 'male', language: '普通话', description: '男声，清晰稳重' },
  { value: 'x4_mingge', label: '明哥', gender: 'male', language: '普通话', description: '男声，适合长者和文化讲解' },
  { value: 'x4_lingxiaoqi_assist', label: '聆小琪-助理', gender: 'female', language: '普通话', description: '女声，新版助理音色' },
  { value: 'x4_chaoge', label: '超哥4.0', gender: 'male', language: '普通话', description: '男声，饱满有感染力' },
  { value: 'x4_panting', label: '小娟-甜美4.0', gender: 'female', language: '普通话', description: '女声，甜美服务型讲解' },
  { value: 'x4_lingxiaoyue_oral', label: '聆小玥', gender: 'female', language: '普通话', description: '女声，亲和自然' },
  { value: 'x4_lingyuyan_oral', label: '聆玉言', gender: 'female', language: '普通话', description: '女声，清晰讲述' },
  { value: 'x4_lingyuzhao_oral', label: '聆玉昭', gender: 'female', language: '普通话', description: '女声，端庄讲解' },
  { value: 'x4_lingfeiyi_oral', label: '聆飞逸', gender: 'male', language: '普通话', description: '男声，适合文化故事' },
  { value: 'x4_lingfeizhe_oral', label: '聆飞哲', gender: 'male', language: '普通话', description: '男声，适合佛法故事线' },
  { value: 'x4_lingxiaoxuan_oral', label: '聆小璇', gender: 'female', language: '普通话', description: '女声，默认讲解音色' },
  { value: 'x4_lingxiaoxuan_em_v2', label: '聆小璇-多情感', gender: 'female', language: '普通话', description: '女声，多情感旧版' },
  { value: 'yezi', label: '叶子', gender: 'female', language: '普通话', description: '女声，轻快自然' },
  { value: 'x5_lingfeiyi_flow', label: '聆飞逸-极速超拟人', gender: 'male', language: '普通话', description: '男声，极速超拟人' },
  { value: 'x5_lingxiaoyue_flow', label: '聆小玥-极速超拟人', gender: 'female', language: '普通话', description: '女声，极速超拟人' },
  { value: 'x4_lingxiaoyue_oral_emo', label: '聆小玥-超拟人-多情感', gender: 'female', language: '普通话', description: '女声，多情感讲解' },
  { value: 'x4_yifei', label: '一菲', gender: 'female', language: '普通话', description: '女声，明亮自然' },
  { value: 'x4_lingbosong', label: '聆伯松', gender: 'male', language: '普通话', description: '男声，儒雅沉稳' },
  { value: 'e622bf6_ttsclone-xfyousheng-cjvmm', label: '朗霄', gender: 'male', language: '普通话', description: '男声，克隆音色' },
  { value: 'cnedfe421_ttsclone-xfyousheng-meqoc', label: '启铭', gender: 'male', language: '普通话', description: '男声，克隆音色' },
  { value: 'cneb69c11_ttsclone-xfyousheng-lnovq', label: '悦宁', gender: 'female', language: '普通话', description: '女声，克隆音色' },
  { value: '9cf3525_ttsclone-xfyousheng-xvbyk', label: '雅昕-pro', gender: 'female', language: '普通话', description: '女声，克隆音色' },
  { value: '1140051_ttsclone-xfyousheng-pwyie', label: '欣畅', gender: 'female', language: '普通话', description: '女声，克隆音色' },
  { value: 'db9983d_ttsclone-xfyousheng-matbl', label: '雅晨', gender: 'female', language: '普通话', description: '女声，克隆音色' },
  { value: '19f8a3f_ttsclone-xfyousheng-exhrq', label: '雅夕', gender: 'female', language: '普通话', description: '女声，克隆音色' },
  { value: 'x_Steve', label: 'Steve-美式英语', gender: 'male', language: '英语', description: '男声，美式英语' },
  { value: 'x4_EnUs_Lindsay_assist', label: 'Linda', gender: 'female', language: '英语', description: '女声，美式英语助理' },
  { value: 'x4_EnUs_Catherine_profnews', label: 'Catherine4.0', gender: 'female', language: '英语', description: '女声，美式英语播报' },
  { value: 'x4_EnUs_Laura_education', label: 'Laura4.0', gender: 'female', language: '英语', description: '女声，美式英语教育场景' },
  { value: 'x4_EnUk_Amanda_education', label: 'Amanda-英式英语', gender: 'female', language: '英语', description: '女声，英式英语教育场景' },
  { value: 'x4_enuk_ashleigh_assist', label: 'Alice-英式英语', gender: 'female', language: '英语', description: '女声，英式英语助理' },
  { value: 'x4_EnUk_Lydia_edu', label: 'Lydia-英式英语', gender: 'female', language: '英语', description: '女声，英式英语教育场景' },
  { value: 'x2_engam_ryan', label: 'Ryan2.0-美式英语', gender: 'male', language: '英语', description: '男声，美式英语' },
  { value: 'x4_EnUs_Grant_emo', label: 'Grant', gender: 'male', language: '英语', description: '男声，英语多情感' },
  { value: 'x2_jajp_zhongcun', label: '日语中村樱', gender: 'female', language: '日语', description: '女声，日语' },
  { value: 'x4_jajp_zhongcun_assist', label: '中村樱', gender: 'female', language: '日语', description: '女声，日语助理' },
  { value: 'x2_frrgm_lisa', label: 'Lisa-法语', gender: 'female', language: '法语', description: '女声，法语' },
  { value: 'x2_mariane', label: 'Mariane-法语', gender: 'female', language: '法语', description: '女声，法语' },
  { value: 'x2_aren_rania', label: 'Rania-阿拉伯语', gender: 'female', language: '阿拉伯语', description: '女声，阿拉伯语' },
  { value: 'x2_aren_toufic', label: 'Toufic-阿拉伯语', gender: 'male', language: '阿拉伯语', description: '男声，阿拉伯语' },
  { value: 'x4_ctncn_xiaomei_profnews', label: '晓梅-粤语', gender: 'female', language: '粤语/普通话', description: '女声，粤语与普通话' },
  { value: 'x4_KoKr_Kyung_assist', label: 'Kyung-韩语', gender: 'male', language: '韩语', description: '男声，韩语助理' },
  { value: 'x2_kokr_miya', label: 'Miya-韩语', gender: 'female', language: '韩语', description: '女声，韩语' },
  { value: 'x2_ruru_evgenii', label: 'Evgenii-俄语', gender: 'male', language: '俄语', description: '男声，俄语' },
  { value: 'x2_ruru_keshu', label: 'Keshu-俄语', gender: 'female', language: '俄语', description: '女声，俄语' },
]

const emotionOptions = [
  { value: 'lively', label: '活泼生动' },
  { value: 'solemn', label: '庄严肃穆' },
  { value: 'warm', label: '温暖亲切' },
  { value: 'elegant', label: '优雅知性' },
  { value: 'professional', label: '专业严谨' },
]

const spotOptions = [
  '景区入口',
  '灵山大照壁',
  '五明桥',
  '佛足坛',
  '五智门',
  '菩提大道',
  '九龙灌浴',
  '阿育王柱',
  '祥符禅寺',
  '灵山大佛',
  '佛教文化博览馆',
  '灵山梵宫',
  '五印坛城',
  '曼飞龙塔',
  '无尽意斋',
]

const avatarIdOptions: Array<{ value: string; label: string; gender: Gender; costume?: string; note?: string }> = [
  { value: '201165002', label: '昭昭-4.0', gender: 'female' },
  { value: '201355001', label: '林靖', gender: 'male', note: '旧服务资源，新服务实测不兼容' },
  { value: '201354001', label: '林延', gender: 'male', note: '旧服务资源，新服务实测不兼容' },
  { value: '111204004', label: '知夏', gender: 'female' },
  { value: '111182004', label: '明朗', gender: 'male', costume: '新中式雅士套装' },
  { value: '111259001', label: '雨桐', gender: 'female', costume: '国风轻礼服' },
  { value: '111182003', label: '明朗', gender: 'male' },
  { value: '111260002', label: '雨菲', gender: 'female' },
  { value: '111283001', label: '雨汐', gender: 'female' },
  { value: '111286001', label: '明泽', gender: 'male', costume: '新中式文化讲解套装' },
  { value: '111306001', label: '婉柠', gender: 'female' },
  { value: '111310001', label: '婉栀', gender: 'female' },
  { value: '110018011', label: '依倩', gender: 'female' },
  { value: '111322001', label: '舒窈-唐装女生', gender: 'female', costume: '唐风襦裙', note: '推荐默认' },
  { value: '201320001', label: '舒然-唐装', gender: 'female', note: '旧服务资源，新服务实测不兼容' },
  { value: '201329001', label: '苏言', gender: 'female' },
  { value: '201343001', label: '玥瑶', gender: 'female' },
  { value: '110017006', label: '马可', gender: 'male' },
  { value: '110592026', label: '明轩', gender: 'male' },
  { value: '110117005', label: '晓姿', gender: 'female' },
  { value: '110264001', label: '晓雯', gender: 'female' },
  { value: '110005011', label: '晓依', gender: 'female' },
  { value: '110332017', label: '沐沐', gender: 'female' },
  { value: '111140001', label: '风屿', gender: 'male', costume: '国风文士长衫' },
  { value: '110026013', label: '伊凡', gender: 'male' },
  { value: '118801001', label: '依丹', gender: 'female' },
  { value: '110314007', label: '晓宁', gender: 'female' },
  { value: '110022006', label: '晓云', gender: 'female' },
  { value: '111204007', label: '安怡', gender: 'female' },
  { value: '201347001', label: '一诺', gender: 'female' },
]

const actionLibrary = [
  { name: '打招呼', code: 'A_U_hello_O', scene: '开场接待' },
  { name: '抚胸礼', code: 'A_X_jingli_O', scene: '致谢/礼仪' },
  { name: '托下巴思考', code: 'A_RLH_Scratch_O', scene: 'AI思考中' },
  { name: '双手打开欢迎', code: 'A_RLH_welcome_O', scene: '欢迎/推荐' },
  { name: '双手交流', code: 'A_RLH_sit_talk_xhands_O', scene: '耐心说明' },
  { name: '双手重点强调', code: 'A_RLH_sit_emphasize_xhands_O', scene: '注意事项' },
  { name: '左手向前展示', code: 'A_LH_Show_forward_O', scene: '路线讲解' },
  { name: '左手向左展示', code: 'A_LH_Show_left_O', scene: '左侧指引' },
  { name: '左手向左上展示', code: 'A_LH_Show_left_up_O', scene: '建筑/高处讲解' },
  { name: '左手强调', code: 'A_LH_emphasize2_O', scene: '内容强调' },
  { name: '左手挥手', code: 'A_LH_wave_C', scene: '迎送游客' },
  { name: '双手强调', code: 'A_LRH_emphasize2_O', scene: '重点讲解' },
  { name: '双手连续强调', code: 'A_LRH_emphasize2_twice_O', scene: '关键提醒' },
  { name: '右手点赞', code: 'A_RH_sit_good_O', scene: '正向反馈' },
  { name: '右手加油', code: 'A_RH_sit_encourage_O', scene: '鼓励/任务' },
  { name: '右手向右展示', code: 'A_RH_Show_right_O', scene: '右侧指引' },
  { name: '右手向前展示', code: 'A_RH_Show_forward_O', scene: '前方路线' },
  { name: '右手 OK', code: 'A_RH_ok_O', scene: '确认/文创' },
  { name: '右手强调', code: 'A_RH_emphasize2_O', scene: '内容强调' },
  { name: '右手连续强调', code: 'A_RH_emphasize_twice_O', scene: '连续提醒' },
  { name: '右手转双手强调', code: 'A_RH_emphasize_twice_RLH_O', scene: '长内容转场' },
  { name: '鼓掌', code: 'A_RLH_applaud_C', scene: '故事/完成任务' },
  { name: '右挥手', code: 'A_RH_wave_C', scene: '结束送别' },
]

const initialAvatars: AvatarConfig[] = [
  {
    id: 1,
    code: 'lingxiaochan',
    name: '舒窈',
    title: '轻松导览 · 聆小璇音色',
    description: '唐装女声导游形象，负责入口接待、儿童问答、景点讲解和路线引导，支持回答意图驱动动作。',
    voice: 'x4_lingxiaoxuan_oral',
    vcn: 'x4_lingxiaoxuan_oral',
    emotion: 'lively',
    triggerSpots: ['灵山大照壁', '九龙灌浴', '百子戏弥勒'],
    enabled: true,
    gender: 'female',
    avatarId: '111322001',
    scene: 'XFYUN_AVATAR_SCENE_ID',
    provider: 'xunfei',
    actionPresets: ['A_U_hello_O', 'A_RLH_welcome_O', 'A_RLH_Scratch_O', 'A_RH_wave_C'],
  },
  {
    id: 2,
    code: 'wuchanshi',
    name: '明朗',
    title: '稳重文化讲解 · 明哥音色',
    description: '明朗男声形象，适合研学团队、佛教历史和建筑艺术深度讲解。',
    voice: 'x4_mingge',
    vcn: 'x4_mingge',
    emotion: 'solemn',
    triggerSpots: ['五智门', '菩提大道'],
    enabled: true,
    gender: 'male',
    avatarId: '111182004',
    scene: 'XFYUN_AVATAR_SCENE_ID',
    provider: 'xunfei',
    actionPresets: ['A_X_jingli_O', 'A_LRH_emphasize2_O', 'A_RLH_sit_talk_xhands_O'],
  },
  {
    id: 3,
    code: 'xuanzang',
    name: '风屿',
    title: '历史故事与研学 · 聆飞哲音色',
    description: '风屿男声形象，承担西行文化、历史传说辨析和祥符禅寺剧情线讲解。',
    voice: 'x4_lingfeizhe_oral',
    vcn: 'x4_lingfeizhe_oral',
    emotion: 'solemn',
    triggerSpots: ['佛足坛', '降魔浮雕', '阿育王柱', '祥符禅寺'],
    enabled: true,
    gender: 'male',
    avatarId: '111140001',
    scene: 'XFYUN_AVATAR_SCENE_ID',
    provider: 'xunfei',
    actionPresets: ['A_X_jingli_O', 'A_LH_Show_left_up_O', 'A_LRH_emphasize2_twice_O'],
  },
  {
    id: 4,
    code: 'xiaowan',
    name: '雨桐',
    title: '江南美学与旅拍 · 聆小玥音色',
    description: '唐装江南姑娘形象，负责拍照点位、文创灵感和女性游客导览场景。',
    voice: 'x4_lingxiaoyue_oral_emo',
    vcn: 'x4_lingxiaoyue_oral_emo',
    emotion: 'warm',
    triggerSpots: ['五明桥', '曼飞龙塔', '无尽意斋'],
    enabled: true,
    gender: 'female',
    avatarId: '111259001',
    scene: 'XFYUN_AVATAR_SCENE_ID',
    provider: 'xunfei',
    actionPresets: ['A_RLH_welcome_O', 'A_LH_Show_forward_O', 'A_RH_ok_O'],
  },
  {
    id: 5,
    code: 'zhaopuchu',
    name: '明泽',
    title: '建筑与艺术导览 · 明哥音色',
    description: '明泽男声形象，讲述建筑工艺、景区营建背景和佛教艺术脉络。',
    voice: 'x4_mingge',
    vcn: 'x4_mingge',
    emotion: 'professional',
    triggerSpots: ['灵山大佛', '佛教文化博览馆', '灵山梵宫', '五印坛城'],
    enabled: true,
    gender: 'male',
    avatarId: '111286001',
    scene: 'XFYUN_AVATAR_SCENE_ID',
    provider: 'xunfei',
    actionPresets: ['A_X_jingli_O', 'A_LRH_emphasize2_O'],
  },
]

const roleBlue = '#2d5a87'

const avatarVisuals: Record<string, { image: string; mark: string; tone: string }> = {
  lingxiaochan: { image: '/assets/avatars/lingxiaochan.jpg', mark: '舒', tone: roleBlue },
  wuchanshi: { image: '/assets/avatars/wuchanshi.jpg', mark: '明', tone: roleBlue },
  xuanzang: { image: '/assets/avatars/xuanzang.jpg', mark: '风', tone: roleBlue },
  xiaowan: { image: '/assets/avatars/xiaowan.jpg', mark: '雨', tone: roleBlue },
  zhaopuchu: { image: '/assets/avatars/zhaopuchu.jpg', mark: '明', tone: roleBlue },
}

const normalizeAvatarId = (value: string | undefined) => {
  const raw = (value || '').trim()
  const direct = avatarIdOptions.find((item) => item.value === raw)
  if (direct) return direct.value
  const digitMatch = raw.match(/\d{9}/)
  return digitMatch ? digitMatch[0] : raw
}

const resolveGender = (value: unknown, avatarId?: string, voiceId?: string): Gender => {
  if (value === 'male' || value === 'female') return value
  const normalizedAvatarId = normalizeAvatarId(avatarId)
  const avatarGender = avatarIdOptions.find((item) => item.value === normalizedAvatarId)?.gender
  if (avatarGender) return avatarGender
  return voiceOptions.find((item) => item.value === voiceId)?.gender || 'female'
}

const getAvatarLabel = (avatarId: string) => {
  const normalizedAvatarId = normalizeAvatarId(avatarId)
  const option = avatarIdOptions.find((item) => item.value === normalizedAvatarId)
  return option ? `${option.label} · ${normalizedAvatarId}` : avatarId
}

const getAppearanceBundle = (avatar: AvatarConfig) => {
  const option = avatarIdOptions.find((item) => item.value === normalizeAvatarId(avatar.avatarId))
  return {
    name: avatar.bundleName || `${option?.label || avatar.name}形象与服装套装`,
    costume: avatar.costumeDescription || `${option?.costume || '供应商固定服饰'}，随 Avatar ID 一并切换`,
    verified: Boolean(
      avatar.previewVerifiedAt
      && avatar.previewAvatarId === normalizeAvatarId(avatar.avatarId)
      && avatar.previewVoiceId === avatar.vcn
      && avatar.imageUrl
    ),
  }
}

export default function AvatarConfigPage() {
  const [avatars, setAvatars] = useState<AvatarConfig[]>(initialAvatars)
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [editingAvatar, setEditingAvatar] = useState<AvatarConfig | null>(null)
  const [previewVisible, setPreviewVisible] = useState(false)
  const [previewPayload, setPreviewPayload] = useState<AvatarPreviewPayload | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewSaving, setPreviewSaving] = useState(false)
  const [syncingFromEnv, setSyncingFromEnv] = useState(false)
  const [saving, setSaving] = useState(false)
  const [healthLoading, setHealthLoading] = useState(false)
  const [healthById, setHealthById] = useState<Record<string, AvatarHealth>>({})
  const [form] = Form.useForm()
  const watchedAvatarId = Form.useWatch<string>('avatarId', form)
  const selectedCharacter = avatarIdOptions.find((item) => item.value === normalizeAvatarId(watchedAvatarId))
  const selectedGender = selectedCharacter?.gender || editingAvatar?.gender || 'female'
  const matchingVoiceOptions = voiceOptions.filter((item) => item.gender === selectedGender)
  const availableAvatarOptions = useMemo(() => {
    const currentIds = new Set(avatars.map((item) => normalizeAvatarId(item.avatarId)))
    const verifiedIds = new Set(
      avatars
        .filter((item) => getAppearanceBundle(item).verified)
        .map((item) => normalizeAvatarId(item.avatarId)),
    )
    return avatarIdOptions.filter((item) => currentIds.has(item.value) || verifiedIds.has(item.value))
  }, [avatars])
  const { channel } = useAvatarChannelStatus()
  const visitorOwnsChannel = channel.owner_type === 'visitor'
    && (channel.status === 'occupied' || channel.status === 'revoking')
  const previewBlocked = visitorOwnsChannel || channel.status === 'cooldown'

  const checkedAvatarIds = Object.keys(healthById)
  const healthyAvatarCount = checkedAvatarIds.filter((id) => healthById[id]?.ok).length

  const toApiPayload = (avatar: AvatarConfig) => ({
    name: avatar.name,
    code: avatar.code,
    role_description: avatar.title,
    image_url: avatar.imageUrl || null,
    avatar_id: normalizeAvatarId(avatar.avatarId),
    voice_id: avatar.vcn,
    voice_emotion: avatar.emotion,
    voice_params: {
      provider: avatar.provider,
      quality: computeCompleteness(avatar),
      gender: avatar.gender,
      avatar_label: getAvatarLabel(avatar.avatarId),
      appearance_bundle: {
        name: getAppearanceBundle(avatar).name,
        gender: avatar.gender,
        costume_description: getAppearanceBundle(avatar).costume,
      },
      preview_verified_at: avatar.previewVerifiedAt,
      preview_avatar_id: avatar.previewAvatarId,
      preview_voice_id: avatar.previewVoiceId,
      action_presets: avatar.actionPresets,
    },
    personality_prompt: avatar.description,
    default_greeting: `${avatar.name}已准备好为游客讲解。`,
    trigger_spots: avatar.triggerSpots,
    is_active: avatar.enabled,
    is_default: avatar.code === 'lingxiaochan',
    sort_order: Number(avatar.id) || 0,
  })

  const fromApiPayload = (item: any): AvatarConfig => ({
    id: item.id,
    code: item.code,
    name: item.name,
    title: item.role_description || 'AI 数字人导游',
    description: item.personality_prompt || item.role_description || '',
    voice: item.voice_id || 'x4_lingxiaoxuan_oral',
    vcn: item.voice_id || 'x4_lingxiaoxuan_oral',
    emotion: item.voice_emotion || 'warm',
    triggerSpots: item.trigger_spots || [],
    enabled: item.is_active,
    gender: resolveGender(item.voice_params?.gender, item.avatar_id, item.voice_id),
    avatarId: normalizeAvatarId(item.avatar_id || ''),
    scene: 'XFYUN_AVATAR_SCENE_ID',
    provider: 'xunfei',
    actionPresets: item.voice_params?.action_presets || [],
    imageUrl: item.image_url || undefined,
    bundleName: item.voice_params?.appearance_bundle?.name,
    costumeDescription: item.voice_params?.appearance_bundle?.costume_description,
    previewVerifiedAt: item.voice_params?.preview_verified_at,
    previewAvatarId: item.voice_params?.preview_avatar_id,
    previewVoiceId: item.voice_params?.preview_voice_id,
  })

  const checkAvatarHealth = async (items: AvatarConfig[], showResult = false) => {
    const savedItems = items.filter((item) => typeof item.id === 'string')
    if (!savedItems.length) return
    setHealthLoading(true)
    try {
      const entries = await Promise.all(
        savedItems.map(async (item) => {
          try {
            const health = await api.get<AvatarHealth>(`/admin/avatars/${item.id}/health`, { skipErrorToast: true })
            return [String(item.id), health] as const
          } catch (error) {
            return [
              String(item.id),
              { ok: false, checks: [{ name: 'request', ok: false, detail: getApiErrorMessage(error, '基础配置检查失败') }] },
            ] as const
          }
        }),
      )
      const nextHealth: Record<string, AvatarHealth> = Object.fromEntries(entries)
      setHealthById((previous) => ({ ...previous, ...nextHealth }))
      if (showResult) {
        const passed = Object.values(nextHealth).filter((item) => item.ok).length
        if (passed === savedItems.length) message.success(`${savedItems.length} 个角色的基础配置检查均通过`)
        else message.warning(`${passed}/${savedItems.length} 个角色通过基础检查，请查看角色卡片`)
      }
    } finally {
      setHealthLoading(false)
    }
  }

  const loadAvatars = async () => {
    setLoading(true)
    try {
      let rows = await api.get<any[]>('/admin/avatars')
      if (!rows.length) {
        await Promise.all(initialAvatars.map((avatar) => api.post('/admin/avatars', toApiPayload(avatar))))
        rows = await api.get<any[]>('/admin/avatars')
      }
      const mapped = rows.map(fromApiPayload)
      setAvatars(mapped)
      void checkAvatarHealth(mapped)
    } catch (error) {
      console.error('加载数字人配置失败:', error)
      message.error(getApiErrorMessage(error, '数字人配置接口不可用，当前仅展示前端参考配置'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAvatars()
  }, [])

  const handleSyncFromEnv = () => {
    Modal.confirm({
      title: '从 .env 同步五个数字人？',
      content: '请先重建 API 容器。同步会刷新五个内置角色的 Avatar ID、音色和动作预设，不会改动讯飞密钥或已保存的预览截图。',
      okText: '确认同步',
      cancelText: '取消',
      onOk: async () => {
        setSyncingFromEnv(true)
        try {
          const rows = await api.post<any[]>('/admin/avatars/reset-defaults', undefined, { skipErrorToast: true })
          const mapped = rows.map(fromApiPayload)
          setAvatars(mapped)
          await checkAvatarHealth(mapped)
          message.success('已从 API 容器环境变量同步数字人配置')
        } catch (error) {
          console.error('同步数字人环境变量失败:', error)
          message.error(getApiErrorMessage(error, '同步失败，请确认 API 已按新的 .env 重建'))
          throw error
        } finally {
          setSyncingFromEnv(false)
        }
      },
    })
  }

  const handleEdit = (avatar: AvatarConfig) => {
    setEditingAvatar(avatar)
    form.setFieldsValue({ ...avatar, vcn: avatar.vcn || avatar.voice })
    setModalVisible(true)
  }

  const handleAvatarIdChange = (avatarId: string) => {
    const character = avatarIdOptions.find((item) => item.value === normalizeAvatarId(avatarId))
    if (!character) return
    const currentVcn = form.getFieldValue('vcn')
    const currentVoice = voiceOptions.find((item) => item.value === currentVcn)
    if (!currentVoice || currentVoice.gender !== character.gender) {
      const recommendedVoice = voiceOptions.find((item) => item.gender === character.gender)
      form.setFieldValue('vcn', recommendedVoice?.value)
    }
  }

  const handlePreview = async (avatar: AvatarConfig) => {
    if (previewBlocked) {
      message.warning(channel.message || '游客端正在使用数字人，实时预览暂不可用')
      return
    }
    if (typeof avatar.id !== 'string') {
      message.warning('请先保存该数字人配置，再启动实时预览')
      return
    }
    setPreviewVisible(true)
    setPreviewPayload(null)
    setPreviewLoading(true)
    try {
      const payload = await api.get<AvatarPreviewPayload>(`/admin/avatars/${avatar.id}/preview-config`, { skipErrorToast: true })
      setPreviewPayload(payload)
    } catch (error) {
      console.error('加载数字人预览配置失败:', error)
      message.error(getApiErrorMessage(error, '预览配置加载失败，请检查 Avatar ID 与讯飞授权'))
      setPreviewVisible(false)
    } finally {
      setPreviewLoading(false)
    }
  }

  const handleCapturePreview = async (imageData: string) => {
    if (!previewPayload) return
    const avatar = avatars.find((item) => item.avatarId === previewPayload.avatar_id && item.name === previewPayload.avatar_name)
    if (!avatar || typeof avatar.id !== 'string') return
    setPreviewSaving(true)
    try {
      const updated = await api.post<any>(`/admin/avatars/${avatar.id}/preview-image`, { image_data: imageData })
      const mapped = fromApiPayload(updated)
      setAvatars((prev) => prev.map((item) => (item.id === avatar.id ? mapped : item)))
      setPreviewPayload((prev) => (prev ? { ...prev, image_url: mapped.imageUrl } : prev))
      message.success('已保存当前 WebSDK 画面，并设为该 ID 的头像')
    } catch (error) {
      console.error('保存数字人预览截图失败:', error)
      message.error('预览截图保存失败')
    } finally {
      setPreviewSaving(false)
    }
  }

  const handleToggle = async (id: number | string, enabled: boolean) => {
    setAvatars((prev) => prev.map((item) => (item.id === id ? { ...item, enabled } : item)))
    try {
      if (typeof id === 'string') {
        const updated = await api.put<any>(`/admin/avatars/${id}/enabled?enabled=${enabled}`)
        setAvatars((prev) => prev.map((item) => (item.id === id ? fromApiPayload(updated) : item)))
      }
      message.success(enabled ? '已启用该数字人' : '已禁用该数字人')
    } catch (error) {
      message.error('启停数字人失败')
      await loadAvatars()
    }
  }

  const handleSave = async (previewAfterSave = false) => {
    const values = await form.validateFields()
    if (!editingAvatar) return
    const normalizedAvatarId = normalizeAvatarId(values.avatarId)
    const selectedVoice = voiceOptions.find((item) => item.value === values.vcn)
    const selectedAvatarId = avatarIdOptions.find((item) => item.value === normalizedAvatarId)
    if (!selectedAvatarId) {
      message.error('请选择列表中的数字人形象')
      return
    }
    if (!selectedVoice || selectedVoice.gender !== selectedAvatarId.gender) {
      message.error(selectedAvatarId.gender === 'female' ? '该女性形象只能使用女声音色' : '该男性形象只能使用男声音色')
      return
    }
    const nextAvatar = {
      ...editingAvatar,
      ...values,
      name: editingAvatar.name,
      code: editingAvatar.code,
      voice: values.vcn,
      vcn: values.vcn,
      gender: selectedAvatarId.gender,
      avatarId: normalizedAvatarId,
      provider: 'xunfei' as ProviderType,
      bundleName: `${selectedAvatarId.label}形象与服装套装`,
      costumeDescription: `${selectedAvatarId.costume || '供应商固定服饰'}，随 Avatar ID 一并切换`,
      imageUrl: (
        normalizedAvatarId === normalizeAvatarId(editingAvatar.avatarId)
        && values.vcn === editingAvatar.vcn
      ) ? editingAvatar.imageUrl : undefined,
      previewVerifiedAt: (
        normalizedAvatarId === normalizeAvatarId(editingAvatar.avatarId)
        && values.vcn === editingAvatar.vcn
      ) ? editingAvatar.previewVerifiedAt : undefined,
      previewAvatarId: (
        normalizedAvatarId === normalizeAvatarId(editingAvatar.avatarId)
        && values.vcn === editingAvatar.vcn
      ) ? editingAvatar.previewAvatarId : undefined,
      previewVoiceId: (
        normalizedAvatarId === normalizeAvatarId(editingAvatar.avatarId)
        && values.vcn === editingAvatar.vcn
      ) ? editingAvatar.previewVoiceId : undefined,
    }
    setSaving(true)
    try {
      if (typeof editingAvatar.id === 'string') {
        const updated = await api.put<any>(
          `/admin/avatars/${editingAvatar.id}`,
          toApiPayload(nextAvatar),
          { skipErrorToast: true },
        )
        const mapped = fromApiPayload(updated)
        setAvatars((prev) => prev.map((item) => (item.id === editingAvatar.id ? mapped : item)))
        await checkAvatarHealth([mapped])
        message.success(previewAfterSave ? '配置已保存，正在验证真实画面' : '数字人配置已更新')
        setModalVisible(false)
        if (previewAfterSave) await handlePreview(mapped)
      } else {
        setAvatars((prev) => prev.map((item) => (item.id === editingAvatar.id ? nextAvatar : item)))
        message.success('数字人配置已更新')
        setModalVisible(false)
      }
    } catch (error) {
      message.error(getApiErrorMessage(error, '保存数字人配置失败'))
    } finally {
      setSaving(false)
    }
  }

  const getEmotionConfig = (emotion: string) =>
    emotionOptions.find((item) => item.value === emotion) || emotionOptions[0]

  const getVoiceLabel = (voice: string) =>
    voiceOptions.find((item) => item.value === voice)?.label || voice

  return (
    <div className="avatar-config-page">
      <div style={{ marginBottom: 16 }}>
        <Space align="center" size={12}>
          <RobotOutlined style={{ color: '#2d5a87', fontSize: 24 }} />
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>数字人形象配置</h2>
        </Space>
      </div>

      <Alert
        type={visitorOwnsChannel ? 'warning' : channel.status === 'cooldown' ? 'info' : 'success'}
        showIcon
        style={{ marginBottom: 16 }}
        message={
          visitorOwnsChannel
            ? '唯一数字人通道正由游客端使用，所有实时预览已暂停'
            : channel.status === 'cooldown'
              ? `数字人通道正在完成释放，约 ${Math.max(1, Math.ceil(channel.retry_after_ms / 1000))} 秒后可预览`
              : '唯一数字人通道可用于后台实时预览'
        }
        description={visitorOwnsChannel ? '游客端优先；关闭游客页面并等待冷却后自动恢复。' : channel.message}
      />

      <Card
        variant="borderless"
        style={{
          marginBottom: 16,
          background: 'linear-gradient(135deg, #e3eaeb 0%, #ffffff 62%)',
          border: '1px solid #cfdde6',
        }}
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space wrap size={12} style={{ width: '100%', justifyContent: 'space-between' }}>
            <Badge
              status={healthyAvatarCount === avatars.length && avatars.length > 0 ? 'success' : healthLoading ? 'processing' : 'warning'}
              text={`基础配置检查 ${healthyAvatarCount}/${avatars.length}`}
            />
            <Space wrap>
              <Button
                size="small"
                icon={<ReloadOutlined />}
                loading={healthLoading}
                onClick={() => checkAvatarHealth(avatars, true)}
              >
                重新检查
              </Button>
              <Button size="small" loading={syncingFromEnv} onClick={handleSyncFromEnv}>
                从 .env 重载角色资源
              </Button>
            </Space>
          </Space>
          <Alert
            type="info"
            showIcon
            message="基础检查仅确认配置完整；“实时预览”才验证 Avatar ID 与 VCN 的真实授权。"
          />
        </Space>
      </Card>

      <Row className="avatar-config-grid" gutter={[16, 16]} style={{ opacity: loading ? 0.65 : 1 }}>
        {avatars.map((avatar) => {
          const emotionConfig = getEmotionConfig(avatar.emotion)
          const appearanceBundle = getAppearanceBundle(avatar)
          const color = roleBlue
          const visual = avatarVisuals[avatar.code] || { image: '/assets/scenery/lingshan-scenic.jpg', mark: avatar.name.slice(0, 1), tone: roleBlue }
          const visualImage = avatar.imageUrl || visual.image
          return (
            <Col className="avatar-config-col" xs={24} md={12} xl={8} key={avatar.id}>
              <Card
                className="avatar-role-card"
                hoverable
                variant="borderless"
                style={{
                  borderRadius: 8,
                  overflow: 'hidden',
                  width: '100%',
                  height: '100%',
                  border: avatar.enabled ? '1px solid #cfdde6' : '1px solid #f0f0f0',
                }}
                styles={{ body: { padding: 0, height: '100%', display: 'flex', flexDirection: 'column' } }}
              >
                <div
                  style={{
                    height: 120,
                    padding: 18,
                    color: '#fff',
                    background: `linear-gradient(135deg, ${color} 0%, #1e4367 100%)`,
                    position: 'relative',
                  }}
                >
                  <Space align="start" style={{ width: '100%', justifyContent: 'space-between' }}>
                    <Space align="center">
                      <div
                        style={{
                          width: 68,
                          height: 68,
                          borderRadius: 8,
                          border: '1px solid rgba(255,255,255,0.42)',
                          background: avatar.imageUrl
                            ? `url(${visualImage}) center top / cover`
                            : `linear-gradient(180deg, rgba(0,0,0,0.08), rgba(0,0,0,0.52)), url(${visualImage}) center / cover`,
                          display: 'grid',
                          placeItems: 'center',
                          boxShadow: '0 10px 24px rgba(0,0,0,0.18)',
                        }}
                      >
                        {!avatar.imageUrl && <span
                          style={{
                            width: 38,
                            height: 38,
                            borderRadius: '50%',
                            display: 'grid',
                            placeItems: 'center',
                            background: visual.tone,
                            color: '#fff',
                            fontWeight: 900,
                            border: '2px solid rgba(255,255,255,0.72)',
                          }}
                        >
                          {visual.mark}
                        </span>}
                      </div>
                      <div>
                        <h3 style={{ color: '#fff', margin: 0, fontSize: 20 }}>{avatar.name}</h3>
                        <div style={{ opacity: 0.86, marginTop: 4 }}>{avatar.title}</div>
                      </div>
                    </Space>
                    <Switch
                      checked={avatar.enabled}
                      onChange={(checked) => handleToggle(avatar.id, checked)}
                      checkedChildren="启用"
                      unCheckedChildren="禁用"
                    />
                  </Space>
                  <Tag
                    color={healthById[String(avatar.id)]?.ok ? 'green' : 'orange'}
                    icon={healthById[String(avatar.id)]?.ok ? <CheckCircleOutlined /> : <ReloadOutlined />}
                    style={{ position: 'absolute', right: 18, bottom: 14 }}
                  >
                    {healthById[String(avatar.id)]?.ok ? '基础配置通过' : '待检查'}
                  </Tag>
                </div>

                <div className="avatar-role-card-body" style={{ padding: 18 }}>
                  <p style={{ color: '#667085', lineHeight: 1.7, minHeight: 72, margin: 0 }}>
                    {avatar.description}
                  </p>

                  <Divider style={{ margin: '14px 0' }} />

                  <Space direction="vertical" size={10} style={{ width: '100%' }}>
                    <InfoLine icon={<AudioOutlined />} label="音色" value={`${getVoiceLabel(avatar.voice)} · ${avatar.vcn}`} />
                    <InfoLine icon={<SmileOutlined />} label="情感" value={emotionConfig.label} />
                    <InfoLine icon={<ApiOutlined />} label="服饰" value={appearanceBundle.costume} />
                    <InfoLine icon={<ThunderboltOutlined />} label="动作" value={`${avatar.actionPresets.length} 个预设`} />
                  </Space>

                  <div style={{ marginTop: 12 }}>
                    <Tag
                      color={appearanceBundle.verified ? 'success' : 'warning'}
                      icon={appearanceBundle.verified ? <CheckCircleOutlined /> : undefined}
                    >
                      {appearanceBundle.verified ? '形象、服装与音色已由真实首帧留证' : '当前套装尚未完成真实首帧留证'}
                    </Tag>
                  </div>

                  <div style={{ marginTop: 16 }}>
                    <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                      <span style={{ color: '#667085' }}>演示体验完整度</span>
                      <span style={{ fontWeight: 700 }}>{computeCompleteness(avatar)}%</span>
                    </Space>
                    <Progress percent={computeCompleteness(avatar)} showInfo={false} strokeColor={color} />
                  </div>

                  <Collapse
                    className="avatar-role-details"
                    ghost
                    size="small"
                    items={[{
                      key: 'details',
                      label: `详细编排 · ${avatar.actionPresets.length} 个动作 / ${avatar.triggerSpots.length} 个触发景点`,
                      children: (
                        <Space direction="vertical" size={12} style={{ width: '100%' }}>
                          <div>
                            <div style={{ color: '#667085', marginBottom: 8 }}>
                              <ThunderboltOutlined style={{ marginRight: 8, color: '#2d5a87' }} />
                              已授权动作
                            </div>
                            <Space wrap size={[4, 6]}>
                              {avatar.actionPresets.map((code) => (
                                <Tag color="purple" key={code}>{actionLibrary.find((item) => item.code === code)?.name || code}</Tag>
                              ))}
                            </Space>
                          </div>
                          <div>
                            <div style={{ color: '#667085', marginBottom: 8 }}>
                              <EnvironmentOutlined style={{ marginRight: 8, color: '#2d5a87' }} />
                              自动讲解景点
                            </div>
                            <Space wrap size={[4, 6]}>
                              {avatar.triggerSpots.map((spot) => <Tag key={spot}>{spot}</Tag>)}
                              {!avatar.triggerSpots.length && <Tag>未配置（游客手动选角优先）</Tag>}
                            </Space>
                          </div>
                        </Space>
                      ),
                    }]}
                  />

                  <Space.Compact className="avatar-role-actions" block style={{ marginTop: 16 }}>
                    <Button
                      icon={<EyeOutlined />}
                      onClick={() => handlePreview(avatar)}
                      disabled={previewBlocked}
                      style={{ width: '50%' }}
                    >
                      实时预览
                    </Button>
                    <Button
                      type="primary"
                      ghost
                      icon={<EditOutlined />}
                      onClick={() => handleEdit(avatar)}
                      style={{ width: '50%' }}
                    >
                      编辑配置
                    </Button>
                  </Space.Compact>
                </div>
              </Card>
            </Col>
          )
        })}
      </Row>

      <Card
        className="avatar-action-library"
        variant="borderless"
        title="讯飞数字人动作库"
        extra={<Tag color="purple">{actionLibrary.length} 个动作</Tag>}
        style={{ marginTop: 16, marginBottom: 16 }}
      >
        <Space wrap size={[8, 10]}>
          {actionLibrary.map((action) => (
            <Tooltip key={action.code} title={`${action.code} · ${action.scene}`}>
              <Tag color="processing" icon={<ThunderboltOutlined />}>
                {action.name}
              </Tag>
            </Tooltip>
          ))}
        </Space>
      </Card>

      <Modal
        title={editingAvatar ? `编辑 ${editingAvatar.name}` : '编辑数字人配置'}
        open={modalVisible}
        onOk={() => handleSave(!previewBlocked)}
        onCancel={() => setModalVisible(false)}
        okText={previewBlocked ? '保存配置' : '保存并实时预览'}
        cancelText="取消"
        confirmLoading={saving}
        width={760}
        style={{ top: 24 }}
        styles={{ body: { maxHeight: 'calc(100vh - 180px)', overflowY: 'auto' } }}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Row gutter={16}>
            <Col xs={24} sm={12}>
              <Form.Item name="name" label="角色名称">
                <Input disabled />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item
                name="code"
                label="角色编码"
                tooltip="系统内部稳定键，用于游客端资源与选角映射，不建议修改。"
              >
                <Input disabled />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            name="title"
            label="角色定位"
            tooltip="显示在角色卡片中，一句话说明角色擅长的导览任务。"
            rules={[{ required: true, message: '请输入角色定位' }]}
          >
            <Input />
          </Form.Item>

          <Form.Item
            name="description"
            label="人设与回答风格"
            tooltip="会加入该角色的大模型系统提示词，写清语气、擅长内容和事实边界。"
            rules={[{ required: true, message: '请输入人设描述' }]}
          >
            <Input.TextArea rows={3} maxLength={220} showCount />
          </Form.Item>

          <Row gutter={16}>
            <Col xs={24} sm={16}>
              <Form.Item
                name="avatarId"
                label="形象与服装套装"
                tooltip="服饰随 Avatar ID 固定；选择后自动确定性别并过滤可选音色。"
                rules={[{ required: true, message: '请选择形象与服装套装' }]}
              >
                <Select
                  showSearch
                  optionFilterProp="searchText"
                  onChange={handleAvatarIdChange}
                  options={availableAvatarOptions.map((avatar) => {
                    const verified = avatars.some((item) => (
                      normalizeAvatarId(item.avatarId) === avatar.value && getAppearanceBundle(item).verified
                    ))
                    return {
                    label: `${avatar.label} · ${avatar.costume || '固定服饰'} · ${avatar.gender === 'female' ? '女' : '男'} · ${verified ? '首帧已验证' : '当前使用，待复验'}`,
                    value: avatar.value,
                    searchText: `${avatar.label} ${avatar.value} ${avatar.gender} ${avatar.costume || ''} ${avatar.note || ''}`,
                    disabled: Boolean(avatar.note?.includes('不兼容')),
                  }})}
                />
              </Form.Item>
            </Col>
            <Col xs={24} sm={8}>
              <Form.Item label="形象性别">
                <Input value={selectedGender === 'female' ? '女（由形象确定）' : '男（由形象确定）'} disabled />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={16}>
            <Col xs={24} sm={16}>
              <Form.Item
                name="vcn"
                label={`讯飞音色（${selectedGender === 'female' ? '女声' : '男声'}）`}
                tooltip="仅显示与形象性别一致的音色；授权以保存后的实时预览为准。"
                rules={[{ required: true, message: '请选择音色' }]}
              >
                <Select
                  showSearch
                  optionFilterProp="searchText"
                  options={matchingVoiceOptions.map((voice) => ({
                    label: `${voice.label} · ${voice.language} · ${voice.value}`,
                    value: voice.value,
                    searchText: `${voice.label} ${voice.value} ${voice.language} ${voice.description}`,
                  }))}
                />
              </Form.Item>
            </Col>
            <Col xs={24} sm={8}>
              <Form.Item name="emotion" label="情感风格" rules={[{ required: true }]}>
                <Select
                  options={emotionOptions.map((emotion) => ({
                    label: emotion.label,
                    value: emotion.value,
                  }))}
                />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            name="triggerSpots"
            label="自动讲解景点（可选）"
            tooltip="游客未手动选角时才按位置自动切换角色；手动选择始终优先。"
          >
            <Select
              mode="multiple"
              maxTagCount="responsive"
              placeholder="不选择则不会按景点自动切换到此角色"
              options={spotOptions.map((spot) => ({ label: spot, value: spot }))}
            />
          </Form.Item>

          <Form.Item
            name="actionPresets"
            label="该形象允许使用的动作"
            tooltip="问答仅从勾选动作中选择；不同形象的授权不同，需用实时预览逐项验收。"
            rules={[{ required: true, message: '请选择至少一个动作' }]}
          >
            <Select
              mode="multiple"
              maxTagCount="responsive"
              options={actionLibrary.map((action) => ({
                label: `${action.name} · ${action.scene} · ${action.code}`,
                value: action.code,
              }))}
            />
          </Form.Item>

          <Alert
            type="warning"
            showIcon
            message="接口凭证仅在根目录 .env 维护，不在此保存；数据库角色配置优先于环境变量。"
          />
        </Form>
      </Modal>

      <Modal
        title={previewPayload ? `${previewPayload.avatar_name} · 实时形象预览` : '实时形象预览'}
        open={previewVisible}
        onCancel={() => {
          setPreviewVisible(false)
          setPreviewPayload(null)
        }}
        width={880}
        footer={null}
        destroyOnHidden
      >
        {previewLoading && (
          <div style={{ minHeight: 360, display: 'grid', placeItems: 'center' }}>
            <span style={{ color: '#667085' }}>正在获取签名配置...</span>
          </div>
        )}
        {previewPayload && (
          <AvatarLivePreview
            payload={previewPayload}
            saving={previewSaving}
            onCapture={handleCapturePreview}
          />
        )}
      </Modal>
    </div>
  )
}

function InfoLine({
  icon,
  label,
  value,
  color = '#2d5a87',
}: {
  icon: ReactNode
  label: string
  value: string
  color?: string
}) {
  return (
    <Space align="start">
      <span style={{ color, width: 18 }}>{icon}</span>
      <span style={{ color: '#667085', minWidth: 54 }}>{label}:</span>
      <span style={{ color: '#1f2937', wordBreak: 'break-all' }}>{value}</span>
    </Space>
  )
}
