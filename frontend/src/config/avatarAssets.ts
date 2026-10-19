export const AVATAR_NAME_TO_IMAGE: Record<string, string> = {
  舒窈: '/assets/avatars/lingxiaochan.jpg',
  明朗: '/assets/avatars/wuchanshi.jpg',
  风屿: '/assets/avatars/xuanzang.jpg',
  雨桐: '/assets/avatars/xiaowan.jpg',
  明泽: '/assets/avatars/zhaopuchu.jpg',
}

export function getAvatarImage(name?: string): string {
  return AVATAR_NAME_TO_IMAGE[name || '舒窈'] || AVATAR_NAME_TO_IMAGE.舒窈
}
