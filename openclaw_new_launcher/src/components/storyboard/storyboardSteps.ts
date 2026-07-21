import type { ModuleKey } from './storyboardTypes';

export type ControlKind = 'tag' | 'dropdown' | 'radio' | 'toggle' | 'contentTypes';

export interface OptionGroup {
  category: string;       // matches a key in param-config[module], e.g. "产品/服务类型"
  label: string;          // display label
  hint?: string;
  control: ControlKind;
  multi?: boolean;        // for tag/contentTypes
  module: ModuleKey;
  /**
   * Built-in, always-visible option list. This is the source of truth for what
   * renders in the UI (mirrors video-generation-ui.html / 视频生成九步.docx).
   * param-config.json only carries the *system-prompt hints* that optimize each
   * option; it does NOT decide whether options are visible.
   */
  options: string[];
}

export interface StoryboardStep {
  id: number;
  key: string;
  module: ModuleKey;
  label: string;
  icon: string;
  goal: string;
  hasGenerate?: boolean;   // true for modules 4/5/9
  generateStage?: 'script' | 'storyboard' | 'videoPrompt';
  optionGroups: OptionGroup[];
}

export const STORYBOARD_STEPS: StoryboardStep[] = [
  {
    id: 0,
    key: 'target',
    module: '模块一',
    label: '目标对象',
    icon: '🎯',
    goal: '整个视频制作的中心点。对象可以是产品名称、场景描述或故事文章。',
    optionGroups: [],
  },
  {
    id: 1,
    key: 'm1',
    module: '模块一',
    label: '定位',
    icon: '🎯',
    goal: '产品·竞争力·痛点：从产品/服务出发，想清卖什么、凭什么强、卖给谁。',
    optionGroups: [
      { module: '模块一', category: '产品/服务类型', label: '产品/服务类型', control: 'tag', multi: false, hint: '选择主营业务类型', options: ['实物商品', '虚拟服务', '知识课程', '门店服务', '加盟项目', '本地生活服务', '咨询顾问'] },
      { module: '模块一', category: '所属品类', label: '所属品类', control: 'dropdown', hint: '行业二级分类，可自定义', options: ['食品饮料', '美妆护肤', '服饰', '母婴', '家居', '教育', '美业', '数码3C', '运动健身', '其他'] },
      { module: '模块一', category: '客单价区间', label: '客单价区间', control: 'radio', hint: '影响后续选品策略与变现路径', options: ['＜50元', '50–200元', '200–1000元', '1000–1万', '＞1万'] },
      { module: '模块一', category: '购买/使用场景', label: '购买/使用场景', control: 'tag', multi: true, hint: '客户的消费动机', options: ['日常刚需', '送礼', '应急', '提升型消费', '决策周期长的大件'] },
      { module: '模块一', category: '核心卖点（多选）', label: '核心卖点', control: 'tag', multi: true, hint: '你比别人强在哪里', options: ['价格优势', '品质用料', '效果功效', '服务体验', '稀缺独家', '资质背书', '技术专利', '情感与价值观', '售后保障'] },
      { module: '模块一', category: '竞争力来源', label: '竞争力来源', control: 'tag', multi: true, hint: '优势的底层支撑', options: ['自有供应链或成本', '独家配方或技术', '专业资质与经验', '口碑与服务', '个人经历背书', '规模效应', '原产地'] },
      { module: '模块一', category: '信任状/背书', label: '信任状/背书', control: 'tag', multi: true, hint: '可多选填写', options: ['销量数据', '权威认证', '客户好评', '媒体报道', '从业年限', '名人/机构合作'] },
      { module: '模块一', category: '目标客户画像', label: '目标客户画像', control: 'tag', multi: true, hint: '多维标签组合', options: ['性别', '年龄段', '身份职业', '消费能力', '所在地域'] },
      { module: '模块一', category: '客户核心痛点（多选）', label: '客户核心痛点', control: 'tag', multi: true, hint: '按行业动态推荐', options: ['不知道怎么选', '怕踩坑买错', '觉得太贵', '效果慢或看不到', '不信任商家', '没时间', '用不明白', '面子/身份需求'] },
      { module: '模块一', category: '购买抗拒点', label: '购买抗拒点', control: 'tag', multi: true, hint: '客户犹豫的原因', options: ['价格顾虑', '信任顾虑', '效果顾虑', '决策成本高', '售后担忧'] },
      { module: '模块一', category: '用户身份角色', label: '用户身份角色', control: 'radio', hint: '决定人设气质', options: ['实体店老板', '品牌主理人', '宝妈', '专家顾问', '微商代理', '自由职业'] },
      { module: '模块一', category: '出镜意愿', label: '出镜意愿', control: 'radio', hint: '影响后续生成方式', options: ['真人出镜', '半出镜', '不出镜（数字人）', '不出镜（图文+素材）'] },
    ],
  },
  {
    id: 2,
    key: 'm2',
    module: '模块二',
    label: '内容风格',
    icon: '🎨',
    goal: '内容形态与全局调性：选定主风格与辅助风格，决定后续文案语气、画面调性、拍摄方式与变现路径。',
    optionGroups: [
      { module: '模块二', category: '内容大类', label: '内容大类', control: 'tag', multi: false, hint: '主风格', options: ['知识博主类', '种草测评类', '品牌宣传类', '剧情故事类', '生活 vlog 类', '促销带货类'] },
      { module: '模块二', category: '人设语气', label: '人设语气', control: 'tag', multi: false, hint: '贯穿后续文案语气', options: ['专业权威', '亲切邻家', '幽默调侃', '犀利吐槽', '温柔治愈', '励志正能量'] },
      { module: '模块二', category: '视觉调性', label: '视觉调性', control: 'tag', multi: false, hint: '画面整体风格', options: ['高级简约', '烟火生活感', '精致时尚', '国潮', '科技质感', '明亮清新'] },
      { module: '模块二', category: '风格组合', label: '风格组合', control: 'tag', multi: true, hint: '可选 1 个主风格 + 1 个辅助风格', options: ['知识博主类（主风格）', '种草测评类（主风格）', '品牌宣传类（主风格）', '剧情故事类（主风格）', '生活 vlog 类（主风格）', '促销带货类（主风格）', '知识博主类（辅助风格）', '种草测评类（辅助风格）', '品牌宣传类（辅助风格）', '剧情故事类（辅助风格）', '生活 vlog 类（辅助风格）', '促销带货类（辅助风格）'] },
    ],
  },
  {
    id: 3,
    key: 'm3',
    module: '模块三',
    label: '全案制作',
    icon: '📋',
    goal: '把「定位 + 风格」一键展开为一份可直接执行的完整运营全案，让用户拿到就知道接下来 30/90 天该怎么干。',
    optionGroups: [
      { module: '模块三', category: '可勾选生成的全案板块', label: '全案板块', control: 'tag', multi: true, hint: '勾选要生成的板块', options: ['账号资料', '内容三支柱', '选题库', '成长路径', '变现漏斗', '发布节奏', '对标账号库'] },
      { module: '模块三', category: '全案激进度', label: '全案激进度', control: 'radio', hint: '控制方案的激进程度', options: ['稳健', '平衡', '激进'] },
      { module: '模块三', category: '规划周期', label: '规划周期', control: 'radio', hint: '全案覆盖的时间范围', options: ['30天', '60天', '90天'] },
      { module: '模块三', category: '侧重方向', label: '侧重方向', control: 'radio', hint: '全案核心优先级', options: ['涨粉优先', '变现优先', '品牌优先'] },
    ],
  },
  {
    id: 4,
    key: 'm4',
    module: '模块四',
    label: '文案撰写',
    icon: '✍️',
    goal: '产出「可直接开口念」的完整口播/剧情文案，确定开头钩子、卖点表达与结尾转化引导。',
    hasGenerate: true,
    generateStage: 'script',
    optionGroups: [
      { module: '模块四', category: '视频类型', label: '视频类型', control: 'tag', multi: false, hint: '决定文案整体结构', options: ['口播干货', '剧情短剧', '种草测评', '街访采访', '生活 vlog', '产品讲解', '教程教学', '观点输出'] },
      { module: '模块四', category: '视频时长', label: '视频时长', control: 'radio', hint: '影响文案字数与节奏', options: ['15秒', '30秒', '45秒', '60秒', '90秒', '3分钟以上'] },
      { module: '模块四', category: '开头钩子', label: '开头钩子', control: 'tag', multi: false, hint: '前3秒抓住注意力', options: ['痛点式', '提问式', '悬念式', '数字利益式', '反常识式', '场景代入式', '身份认同式'] },
      { module: '模块四', category: '文案结构', label: '文案结构', control: 'tag', multi: false, hint: '整体叙事框架', options: ['黄金3秒+痛点+方案+案例+引导', 'AIDA', '故事型 SCQA', '清单体', '对比体'] },
      { module: '模块四', category: '转化动作 CTA', label: '转化动作 CTA', control: 'tag', multi: true, hint: '结尾引导用户做什么', options: ['点赞收藏', '关注', '评论区扣「1」', '私信领资料', '点购物车', '到店核销', '加微信'] },
    ],
  },
  {
    id: 5,
    key: 'm5',
    module: '模块五',
    label: '分镜文案',
    icon: '🎬',
    goal: '文案转画面：逐镜拆解并标注每镜所需的素材类型（人物/产品/场景），直接驱动模块六至八的图像生成与模块九的成片。',
    hasGenerate: true,
    generateStage: 'storyboard',
    optionGroups: [
      { module: '模块五', category: '分镜颗粒度', label: '分镜颗粒度', control: 'radio', hint: '控制分镜精细程度', options: ['粗（3–5镜）', '中（6–10镜）', '细（逐句成镜）'] },
      { module: '模块五', category: '拍摄/成片方式', label: '拍摄/成片方式', control: 'tag', multi: false, hint: '决定分镜写法与所需素材', options: ['手机实拍', '数字人口播', 'AI生成画面', '图文素材'] },
      { module: '模块五', category: '节奏卡点', label: '节奏卡点', control: 'radio', hint: '影响单镜时长与切换频率', options: ['慢节奏叙事', '中速', '快节奏强卡点'] },
      { module: '模块五', category: '特效风格', label: '特效风格', control: 'tag', multi: false, hint: '画面特效类型', options: ['无特效', '简约', '动感综艺（花字贴纸）', '电影感', '科技质感'] },
      { module: '模块五', category: '运镜偏好', label: '运镜偏好', control: 'tag', multi: false, hint: '镜头运动方式', options: ['固定机位为主', '含基础运镜', '丰富运镜（推拉摇移跟环绕）'] },
      { module: '模块五', category: '字幕与音效', label: '字幕与音效', control: 'tag', multi: true, hint: '可多选', options: ['生成逐镜字幕', '含音效与卡点提示', '含转场设计'] },
    ],
  },
  {
    id: 6,
    key: 'm6',
    module: '模块六',
    label: '人物图',
    icon: '🧑‍🎨',
    goal: '生成专属 IP 人物形象，并保持跨内容一致，服务出镜/半出镜/不出镜（数字人）等各种需求。',
    optionGroups: [
      { module: '模块六', category: '性别', label: '性别', control: 'tag', multi: false, hint: '基础形象设定', options: ['男', '女'] },
      { module: '模块六', category: '年龄段', label: '年龄段', control: 'tag', multi: false, options: ['20–25', '25–30', '30–40', '40–50', '50岁以上'] },
      { module: '模块六', category: '气质风格', label: '气质风格', control: 'tag', multi: false, hint: '人物整体气质', options: ['专业精英', '亲和邻家', '时尚潮流', '文艺清新', '成熟稳重', '活力元气', '高端奢华'] },
      { module: '模块六', category: '职业着装', label: '职业着装', control: 'tag', multi: false, hint: '匹配行业属性', options: ['正装', '商务休闲', '白大褂工装', '餐饮围裙', '运动装', '日常休闲', '行业制服'] },
      { module: '模块六', category: '表情神态', label: '表情神态', control: 'tag', multi: false, hint: '面部表情风格', options: ['微笑亲和', '自信坚定', '认真专注', '温暖亲切', '活力开朗'] },
      { module: '模块六', category: '画面风格', label: '画面风格', control: 'tag', multi: false, hint: '图片视觉风格', options: ['商业写实', '日系清新', '国潮', '3D 卡通 IP', '职业证件照'] },
      { module: '模块六', category: '画幅', label: '画幅', control: 'tag', multi: false, options: ['9:16', '3:4', '1:1', '16:9'] },
      { module: '模块六', category: '背景', label: '背景', control: 'tag', multi: false, hint: '输出背景', options: ['纯色', '办公室', '门店', '户外', '直播间', '虚化'] },
    ],
  },
  {
    id: 7,
    key: 'm7',
    module: '模块七',
    label: '产品图',
    icon: '📦',
    goal: '生成电商级产品画面，用于视频画面、封面与图文。',
    optionGroups: [
      { module: '模块七', category: '出图类型', label: '出图类型', control: 'tag', multi: true, hint: '选择需要的图片类型', options: ['白底商品图', '场景实拍感', '手持展示', '平铺 flat lay', '使用中演示', '前后对比图', '卖点标注图'] },
      { module: '模块七', category: '产品呈现', label: '产品呈现', control: 'tag', multi: true, hint: '产品展示方式', options: ['单品特写', '组合套装', '包装展示', '细节质感', '使用效果'] },
      { module: '模块七', category: '视觉风格', label: '视觉风格', control: 'tag', multi: false, hint: '整体视觉调性', options: ['电商精致', '生活氛围感', 'ins 风', '高端质感', '促销大字报'] },
      { module: '模块七', category: '背景/道具', label: '背景/道具', control: 'tag', multi: true, hint: '拍摄背景与搭配', options: ['纯色', '大理石', '木纹', '门店', '厨房', '户外', '搭配相关道具'] },
      { module: '模块七', category: '文字标注', label: '文字标注', control: 'tag', multi: true, hint: '是否叠加卖点文字、价格、活动信息', options: ['叠加卖点文字', '叠加价格', '叠加活动信息'] },
      { module: '模块七', category: '画幅比例', label: '画幅比例', control: 'radio', hint: '输出图片比例', options: ['9:16', '1:1', '3:4', '16:9'] },
    ],
  },
  {
    id: 8,
    key: 'm8',
    module: '模块八',
    label: '场景图',
    icon: '🏙️',
    goal: '生成环境素材，可与人物图、产品图合成完整画面。',
    optionGroups: [
      { module: '模块八', category: '场景类型', label: '场景类型', control: 'tag', multi: true, hint: '选择场景环境', options: ['现代办公室', '实体门店', '家居客厅厨房', '户外街景', '直播间', '会议室', '咖啡馆', '工厂车间', '教室', '自然风光'] },
      { module: '模块八', category: '光线氛围', label: '光线氛围', control: 'tag', multi: false, hint: '画面光线风格', options: ['明亮通透', '温馨暖光', '专业冷调', '电影感', '自然日光', '夜景霓虹'] },
      { module: '模块八', category: '画面色调', label: '画面色调', control: 'tag', multi: false, hint: '整体色彩调性', options: ['清新莫兰迪', '高级灰', '暖橙', '冷蓝', '高饱和活力'] },
      { module: '模块八', category: '视觉风格', label: '视觉风格', control: 'tag', multi: false, hint: '图片风格', options: ['写实摄影', '极简', 'ins 风', '国潮', '赛博'] },
      { module: '模块八', category: '画幅', label: '画幅', control: 'tag', multi: false, options: ['9:16', '16:9', '1:1'] },
      { module: '模块八', category: '用途', label: '用途', control: 'tag', multi: true, hint: '输出尺寸与使用场景', options: ['视频背景', '封面', '分镜画面', '主页装修'] },
    ],
  },
  {
    id: 9,
    key: 'm9',
    module: '模块九',
    label: '生成视频',
    icon: '🎞️',
    goal: '整合文案、分镜、人物图、产品图、场景图，组装视频提示词并一键生成视频。',
    hasGenerate: true,
    generateStage: 'videoPrompt',
    optionGroups: [
      { module: '模块九', category: '成片方式', label: '成片方式', control: 'tag', multi: false, hint: '按需选择', options: ['数字人口播成片', '图文/图片成片', 'AI 视频生成', '爆款模板套用', '真人素材智能剪辑'] },
      { module: '模块九', category: '配音音色', label: '配音音色', control: 'dropdown', hint: '选择配音声音', options: ['男声（磁性）', '男声（年轻）', '男声（沉稳）', '女声（甜美）', '女声（知性）', '女声（温柔）', '方言', '情感语气', '克隆我的声音'] },
      { module: '模块九', category: '语速', label: '语速', control: 'radio', hint: '配音语速', options: ['慢', '正常', '快'] },
      { module: '模块九', category: '字幕样式', label: '字幕样式', control: 'tag', multi: false, hint: '字幕显示风格', options: ['综艺花字', '简约白字', '描边大字', '逐字弹出'] },
      { module: '模块九', category: '背景音乐', label: '背景音乐', control: 'tag', multi: false, hint: 'BGM 风格', options: ['热门卡点', '舒缓', '励志', '商务', '搞笑', '智能匹配'] },
      { module: '模块九', category: '转场特效', label: '转场特效', control: 'radio', hint: '镜头转场方式', options: ['无', '简约', '动感', '自动'] },
      { module: '模块九', category: '画幅', label: '画幅', control: 'radio', hint: '输出视频比例', options: ['9:16', '16:9', '1:1'] },
      { module: '模块九', category: '片头尾', label: '片头尾', control: 'tag', multi: true, hint: '片头片尾设置', options: ['品牌 Logo', '关注引导', '无'] },
    ],
  },
];
