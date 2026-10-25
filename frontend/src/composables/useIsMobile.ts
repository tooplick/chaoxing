import { onBeforeUnmount, onMounted, ref } from 'vue'

/** 响应式移动端判断(断点 768px), 供动态绑定 label-position / 弹窗宽度等 */
const isMobile = ref(false)
let mql: MediaQueryList | null = null
let listener: ((e: MediaQueryListEvent) => void) | null = null
let refCount = 0

export function useIsMobile() {
  onMounted(() => {
    refCount++
    if (!mql) {
      mql = window.matchMedia('(max-width: 768px)')
      isMobile.value = mql.matches
      listener = (e) => (isMobile.value = e.matches)
      mql.addEventListener('change', listener)
    }
  })
  onBeforeUnmount(() => {
    refCount--
    if (refCount === 0 && mql && listener) {
      mql.removeEventListener('change', listener)
      mql = null
      listener = null
    }
  })
  return { isMobile }
}
