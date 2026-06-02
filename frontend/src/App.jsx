import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, MessageCirclePlus, SendHorizontal, Share2, Copy, Check } from "lucide-react";

const APP_NAME = "周末行程助手";

const GUESS_CARDS = [
  {
    primaryIntent: "outdoor_walk",
    title: "🌿 自然漫步，来一场户外散心",
    prefix: "世纪公园的",
    highlight: "绣球花开得正盛",
    suffix: "，这周末是花期尾巴了，想拍照的要抓紧。走走停停刚好半天，旁边吃饭也方便。",
    chips: ["户外散心", "拍照打卡", "半天刚好"],
    prompt: "想在上海安排一个周末半天的户外散心行程，最好能拍照，走走停停不要太累",
    impliedConstraints: {
      poi_category_filter: ["户外休闲.公园"],
      companion_context_candidates: ["solo", "couple", "family_with_children", "friends"],
      context_modifiers: ["weather_dependent", "photo_spot"],
    },
  },
  {
    primaryIntent: "meal",
    title: "🍽️ 犒劳自己，吃顿好的",
    prefix: "武康路新开了一家",
    highlight: "黑珍珠粤菜馆",
    suffix: "，上个月刚上榜，趁现在还没太火可以先去。人均200左右，周末值得。",
    chips: ["吃顿好的", "新上榜", "适合约饭"],
    prompt: "想在上海周末吃顿好的，人均200左右，可以安排一顿适合约饭的餐厅",
    impliedConstraints: {
      poi_category_filter: ["美食.粤菜"],
      companion_context_candidates: ["couple", "friends", "solo"],
      context_modifiers: ["high_budget"],
    },
  },
  {
    primaryIntent: "culture_experience",
    title: "🎨 看展逛逛，随便晃晃",
    prefix: "上生·新所开了",
    highlight: "「路易斯·韦恩」猫猫插画展",
    suffix: "，展不大但很出片，逛完旁边就是番禺路咖啡街，适合放松。",
    chips: ["看展", "低体力", "咖啡顺路"],
    prompt: "想在上海安排一个轻松看展行程，低体力、适合拍照，最好附近还能喝咖啡",
    impliedConstraints: {
      poi_category_filter: ["文化体验.展览"],
      companion_context_candidates: ["solo", "couple", "friends"],
      context_modifiers: ["photo_spot", "low_energy"],
    },
  },
];

const LABELS = {
  solo: "独处",
  couple: "情侣",
  family_with_children: "亲子同行",
  family_with_elderly: "带老人",
  friends: "朋友",
  colleagues: "同事",
  pet: "带宠物",
  mixed_plan: "吃饭+活动",
  parent_child: "亲子活动",
  meal: "只吃饭",
  culture_experience: "文化体验",
  indoor_entertainment: "室内娱乐",
  outdoor_walk: "户外散步",
  weather_dependent: "看天气",
  high_budget: "预算充足",
  cafe_tea: "咖啡茶饮",
  wellness_relax: "放松疗愈",
  short_trip: "周边短途",
  rainy_day: "下雨",
  low_budget: "低预算",
  low_energy: "少费力",
  quiet: "安静",
  lively: "热闹",
  photo_spot: "拍照打卡",
  no_reservation: "不想预约",
  parking_needed: "需要停车",
  near_subway: "地铁方便",
  low_walking: "少步行",
  queue_sensitive: "不想排队",
  child_safety: "儿童安全",
  elder_mobility: "老人友好",
  budget_cap: "预算上限",
  time_window: "时间窗口",
  route_smoothness: "路线顺",
  place_quality: "地点质量",
  food_quality: "餐饮质量",
  full_day: "全天",
};

function label(value) {
  return LABELS[value] || value;
}

function getDurationText(minutes) {
  if (!minutes) return "待确认";
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours && rest) return `${hours}小时${rest}分`;
  if (hours) return `${hours}小时`;
  return `${rest}分钟`;
}

const TRANSPORT_INFO = {
  driving: { icon: "🚗", label: "驾车" },
  transit: { icon: "🚇", label: "地铁/公交" },
  taxi: { icon: "🚕", label: "打车" },
  bike_walk: { icon: "🚶", label: "骑行/步行" },
};

const STOP_TYPE_META = {
  activity: { icon: "📍", badge: "活动", badgeClass: "badge-activity" },
  meal: { icon: "🍽️", badge: "餐饮", badgeClass: "badge-meal" },
};

/**
 * 从 timeline / route_infos 中构建展示用的行程站点列表。
 * 每个站点包含：名称、地点、时间、标签、到达该站的通勤信息。
 */
function buildRouteStops(plan, request) {
  const timeline = plan.timeline || [];
  const activities = plan.activities || [];
  const restaurant = plan.restaurant;
  const routeInfos = plan.route_infos || [];
  const transportMode = request?.transportation || "driving";

  // 先收集所有 activity/meal 类型的站点
  const rawStops = [];
  for (let i = 0; i < timeline.length; i++) {
    const item = timeline[i];
    if (item.type !== "activity" && item.type !== "meal") continue;
    rawStops.push({ ...item, _idx: i });
  }

  if (rawStops.length === 0) return [];

  const stops = rawStops.map((item, stopIndex) => {
    const isActivity = item.type === "activity";
    const isMeal = item.type === "meal";
    const [startTime, endTime] = (item.time || "").split("-");

    // 匹配活动/餐厅的富数据
    let enriched = {};
    if (isActivity) {
      const matched = activities.find(
        (a) => item.activity.includes(a.name) || a.name.includes(item.activity),
      );
      if (matched) {
        enriched = {
          tags: matched.tags || [],
          childFriendly: matched.child_friendly,
          needBooking: matched.need_booking,
          locationDetail: matched.location,
          durationMinutes: matched.duration_minutes,
          pricePerPerson: matched.price_per_person,
        };
      }
    } else if (isMeal && restaurant) {
      enriched = {
        cuisineType: restaurant.cuisine_type,
        locationDetail: restaurant.location,
        pricePerPerson: restaurant.price_per_person,
        tags: [],
      };
    }

    // 通勤信息：第一个站点无 commute，后续站点从 route_infos 中匹配
    let commute = null;
    if (stopIndex > 0 && routeInfos.length > 0) {
      // route_infos 结构: [home→act1, act1→act2?, last_act→restaurant, restaurant→home]
      // 站点间通勤对应 route_infos 的第 stopIndex 项（当只有一个活动时）
      // 或从 route_infos 中找 "to" 匹配本站 location 的条目
      const route = routeInfos.find(
        (r) => r.to === item.location || (item.location && item.location.includes(r.to)),
      );
      if (route) {
        commute = {
          travelMinutes: route.travel_minutes,
          distanceKm: route.distance_km,
          transportation: transportMode,
        };
      } else {
        // fallback：从 timeline 中取前一个 travel 项的耗时
        const prevItem = timeline[item._idx - 1];
        if (prevItem && prevItem.type === "travel") {
          const match = (prevItem.description || prevItem.activity || "").match(/(\d+)/);
          commute = {
            travelMinutes: match ? parseInt(match[1], 10) : null,
            distanceKm: null,
            transportation: transportMode,
          };
        }
      }
    }

    return {
      type: item.type,
      name: isMeal && restaurant ? restaurant.name : item.activity,
      rawActivity: item.activity,
      location: item.location,
      startTime,
      endTime,
      commute,
      ...enriched,
    };
  });

  return stops;
}

function getNowText() {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date());
}

// ==================== Q1-Q3 Slot Configs ====================

const COMPANION_CHIPS = [
  { label: "独自出行", value: "solo" },
  { label: "情侣出行", value: "couple" },
  { label: "朋友出行", value: "friends" },
  { label: "家庭带娃", value: "family_with_children" },
  { label: "带老人", value: "family_with_elderly" },
  { label: "同事出行", value: "colleagues" },
  { label: "带宠物", value: "pet" },
];

const TIME_CHIPS = [
  { label: "现在就走", value: "now" },
  { label: "上午", value: "morning" },
  { label: "下午", value: "afternoon" },
  { label: "全天", value: "full_day" },
];

const TRANSPORT_CHIPS = [
  { label: "自驾", value: "driving" },
  { label: "地铁/公交", value: "transit" },
  { label: "打车", value: "taxi" },
  { label: "骑行/步行", value: "bike_walk" },
];

const TRANSPORT_MODIFIERS = {
  driving: ["parking_needed"],
  transit: ["near_subway"],
  taxi: [],
  bike_walk: ["low_walking"],
};

// ==================== Follow-up Sub-Options ====================

const SLOT_OPTIONS = {
  people_count: [
    { label: "就我一个", value: 1 },
    { label: "两人同行", value: 2 },
    { label: "3-5人", value: "3-5" },
    { label: "组团出行", value: "6+" },
  ],
  budget_level: [
    { label: "人均100以内", value: "low" },
    { label: "人均100-200", value: "medium" },
    { label: "人均200-300", value: "medium_high" },
    { label: "人均300以上", value: "high" },
  ],
  child_age: [
    { label: "0-3岁", value: "0-3" },
    { label: "4-6岁", value: "4-6" },
    { label: "7-12岁", value: "7-12" },
    { label: "12岁以上", value: "12+" },
  ],
  cuisine_type: [
    { label: "火锅", value: "hotpot" },
    { label: "日料", value: "japanese" },
    { label: "粤菜/本帮菜", value: "cantonese" },
    { label: "西餐", value: "western" },
    { label: "烧烤", value: "bbq" },
    { label: "不挑食", value: "any" },
  ],
  food_preference: [
    { label: "火锅", value: "hotpot" },
    { label: "日料", value: "japanese" },
    { label: "粤菜/本帮菜", value: "cantonese" },
    { label: "西餐", value: "western" },
    { label: "烧烤", value: "bbq" },
    { label: "轻食健康餐", value: "healthy" },
  ],
  activity_preference: [
    { label: "户外走走", value: "outdoor" },
    { label: "看展逛逛", value: "culture" },
    { label: "吃顿好的", value: "food" },
    { label: "轻松放松", value: "relax" },
    { label: "室内娱乐", value: "indoor" },
  ],
  atmosphere: [
    { label: "安静舒服", value: "quiet" },
    { label: "热闹有氛围", value: "lively" },
    { label: "浪漫私密", value: "romantic" },
  ],
  max_distance: [
    { label: "30分钟内", value: "nearby" },
    { label: "1小时内", value: "medium" },
    { label: "远点也行", value: "far" },
  ],
  // Boolean-style: two options
  parent_child: [
    { label: "需要亲子设施", value: true },
    { label: "不需要", value: false },
  ],
  parking_needed: [
    { label: "必须好停车", value: true },
    { label: "无所谓", value: false },
  ],
  near_subway: [
    { label: "必须近地铁", value: true },
    { label: "无所谓", value: false },
  ],
  pet_allowed: [
    { label: "必须能带宠物", value: true },
    { label: "无所谓", value: false },
  ],
  low_energy: [
    { label: "不想太累", value: true },
    { label: "可以接受一定体力", value: false },
  ],
  photo_spot: [
    { label: "要出片好看", value: true },
    { label: "无所谓", value: false },
  ],
  quiet: [
    { label: "要安静", value: true },
    { label: "无所谓", value: false },
  ],
  lively: [
    { label: "要热闹", value: true },
    { label: "无所谓", value: false },
  ],
  high_budget: [
    { label: "预算充足", value: true },
    { label: "适中就好", value: false },
  ],
  low_budget: [
    { label: "经济实惠", value: true },
    { label: "适中就好", value: false },
  ],
};

function getSlotOptions(slotHint) {
  // Try exact match first, then try individual hints when comma-separated
  const hints = slotHint.split(/[,，]\s*/).map((h) => h.trim());
  for (const hint of hints) {
    if (SLOT_OPTIONS[hint]) return SLOT_OPTIONS[hint];
  }
  // Fallback: generic yes/no
  return [
    { label: "是", value: true },
    { label: "否", value: false },
  ];
}

// ==================== Components ====================

function StatusBar() {
  const now = useMemo(() => getNowText(), []);
  return (
    <div className="status-bar">
      <span>{now}</span>
      <div className="status-icons">
        <span className="signal">
          <i />
          <i />
          <i />
          <i />
        </span>
        <span>5G</span>
        <span className="battery" />
      </div>
    </div>
  );
}

function Header({ onReset }) {
  return (
    <header className="phone-header">
      <button className="icon-button" type="button" aria-label="返回">
        <ChevronLeft size={24} strokeWidth={2.5} />
      </button>
      <div className="header-title">
        <strong>{APP_NAME}</strong>
        <span>● 小团</span>
      </div>
      <button className="new-chat" type="button" onClick={onReset}>
        <MessageCirclePlus size={18} strokeWidth={2.4} />
        <span>新建对话</span>
      </button>
    </header>
  );
}

function EmptyState({ onPick }) {
  return (
    <div className="empty-state">
      <h1>你想怎么安排这段空闲时间？</h1>
      <p>告诉我时间、地点、同行人、预算或偏好。我会返回一张可执行的中国本地生活行程卡片。</p>
      <div className="examples">
        {GUESS_CARDS.map((card) => (
          <button
            className="guess-card"
            key={card.primaryIntent}
            type="button"
            onClick={() => onPick(card.prompt)}
          >
            <span className="guess-title">{card.title}</span>
            <span className="guess-copy">
              {card.prefix}
              <strong>{card.highlight}</strong>
              {card.suffix}
            </span>
            <span className="guess-chips">
              {card.chips.map((chip) => (
                <em key={chip}>{chip}</em>
              ))}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function StructuredPanel({ slots, onSlotSelect, onSubmit, disabled }) {
  const companionSelected = (slots.companion_context || []).length > 0;
  const timeSelected = !!slots.time_window;
  const transportSelected = !!slots.transportation;
  const allReady = companionSelected && timeSelected && transportSelected;

  return (
    <div className="structured-panel">
      <h2>快速告诉我你的偏好</h2>
      <p className="panel-subtitle">选好后小团会帮你补全剩下的细节</p>

      <div className="slot-question">
        <label>👥 和谁一起</label>
        <div className="slot-chips">
          {COMPANION_CHIPS.map((chip) => (
            <button
              key={chip.value}
              className={`slot-chip${(slots.companion_context || []).includes(chip.value) ? " selected" : ""}`}
              type="button"
              onClick={() => onSlotSelect("companion_context", chip.value)}
              disabled={disabled}
            >
              {chip.label}
            </button>
          ))}
        </div>
      </div>

      <div className="slot-question">
        <label>🕐 什么时候</label>
        <div className="slot-chips">
          {TIME_CHIPS.map((chip) => (
            <button
              key={chip.value}
              className={`slot-chip${slots.time_window === chip.value ? " selected" : ""}`}
              type="button"
              onClick={() => onSlotSelect("time_window", chip.value)}
              disabled={disabled}
            >
              {chip.label}
            </button>
          ))}
        </div>
      </div>

      <div className="slot-question">
        <label>🚗 怎么过去</label>
        <div className="slot-chips">
          {TRANSPORT_CHIPS.map((chip) => (
            <button
              key={chip.value}
              className={`slot-chip${slots.transportation === chip.value ? " selected" : ""}`}
              type="button"
              onClick={() => onSlotSelect("transportation", chip.value)}
              disabled={disabled}
            >
              {chip.label}
            </button>
          ))}
        </div>
      </div>

      <button
        className="slot-submit"
        type="button"
        disabled={!allReady || disabled}
        onClick={onSubmit}
      >
        {allReady ? "确认提交" : "请完成以上选择"}
      </button>
    </div>
  );
}

function KangarooLoader() {
  return (
    <div className="kangaroo-loader">
      <div className="kangaroo-card">
        <div className="card-label">推荐方案</div>
        <div className="kangaroo-lines">
          <span />
          <span />
          <span />
        </div>
      </div>
      <div className="kangaroo-track">
        <span className="kangaroo-runner">🦘</span>
      </div>
      <div className="kangaroo-shadow" />
      <p className="kangaroo-text">
        小团正在分析你的需求<span className="dots" />
      </p>
    </div>
  );
}

function Q1Summary({ slots }) {
  const companionLabels = {
    solo: "独自出行", couple: "情侣出行", friends: "朋友出行",
    family_with_children: "家庭带娃", family_with_elderly: "带老人",
    colleagues: "同事出行", pet: "带宠物",
  };
  const timeLabels = {
    now: "现在就走", morning: "上午", afternoon: "下午", full_day: "全天",
  };
  const transportLabels = {
    driving: "自驾", transit: "地铁/公交", taxi: "打车", bike_walk: "骑行/步行",
  };

  const companion = (slots.companion_context || []).map((c) => companionLabels[c] || c).join("、") || "未选择";
  const time = timeLabels[slots.time_window] || "未选择";
  const transport = transportLabels[slots.transportation] || "未选择";

  return (
    <div className="q1-summary">
      <span className="q1-summary-item">👥 {companion}</span>
      <span className="q1-summary-divider" />
      <span className="q1-summary-item">🕐 {time}</span>
      <span className="q1-summary-divider" />
      <span className="q1-summary-item">🚗 {transport}</span>
    </div>
  );
}

function GuessSentences({ sentences, onSentenceClick, disabled, animatingSentence }) {
  if (!sentences || sentences.length === 0) return null;

  return (
    <div className="guess-section">
      <h3>我猜你可能想要这样</h3>
      <p className="guess-subtitle">点击猜测句叠加到对话框，可修改后发送</p>
      <div className="guess-sentences">
        {sentences.map((s) => {
          const isAnimating = animatingSentence?.text === s.text;

          return (
            <button
              key={s.text}
              className={`guess-sentence${isAnimating ? " animating" : ""}`}
              type="button"
              onClick={(e) => onSentenceClick(s, e)}
              disabled={disabled || !!animatingSentence}
            >
              {s.text}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// Flying sentence clone for slide animation
function FlyingSentence({ animatingSentence }) {
  if (!animatingSentence) return null;

  return (
    <div
      className="flying-sentence"
      style={{
        left: animatingSentence.startX,
        top: animatingSentence.startY,
        width: animatingSentence.startWidth,
        height: animatingSentence.startHeight,
      }}
    >
      {animatingSentence.text}
    </div>
  );
}

function UserBubble({ content }) {
  return (
    <div className="message-row user-row">
      <div className="user-bubble">{content}</div>
    </div>
  );
}

function LoadingCard() {
  return (
    <div className="plan-card loading-card">
      <div className="card-label">推荐方案</div>
      <div className="loading-lines">
        <span />
        <span />
        <span />
      </div>
    </div>
  );
}

function MetaBox({ label: title, value }) {
  return (
    <div className="meta-box">
      <span>{title}</span>
      <strong>{value || "待确认"}</strong>
    </div>
  );
}

function TemplateCards({ cards, onSelect, loading, selectedId }) {
  if (loading) {
    return (
      <div className="template-cards-section">
        <h3>正在生成风格推荐...</h3>
        <div className="template-loading">
          <span className="template-loading-card" />
          <span className="template-loading-card" />
          <span className="template-loading-card" />
        </div>
      </div>
    );
  }

  if (!cards || cards.length === 0) return null;

  return (
    <div className="template-cards-section">
      <h3>选一个你喜欢的风格吧</h3>
      <p className="template-subtitle">我会根据你的选择锁定偏好，生成更精准的方案</p>
      <div className="template-cards-grid">
        {cards.map((card) => {
          const isSelected = selectedId === card.card_id;
          return (
            <button
              key={card.card_id}
              className={`template-card${isSelected ? " selected" : ""}`}
              type="button"
              onClick={() => onSelect(card.card_id)}
              disabled={!!selectedId}
            >
              <div className="template-card-title">
                {card.title}
                {card.recommended && <span className="template-card-recommend">推荐</span>}
              </div>
              <p className="template-card-desc">{card.description}</p>
              <div className="template-card-chips">
                {(card.tags || []).map((tag) => (
                  <em key={tag}>{tag}</em>
                ))}
              </div>
              {card.example_content && (
                <div className="template-card-example">
                  <span>例如</span>
                  <p>{card.example_content}</p>
                </div>
              )}
              {isSelected && <div className="template-card-check">✓</div>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function PlanCard({ result, onShare, shareLoading }) {
  const plan = result?.best_plan || {};
  const request = result?.request || {};
  const companion = (request.companion_context || []).map(label).join("、") || label(request.companions);
  const intent = label(request.primary_intent || request.scenario_type || "mixed_plan");
  const chips = [
    ...(request.context_modifiers || []),
    ...(request.hard_constraints || []),
    ...(request.soft_preferences || []),
  ]
    .filter(Boolean)
    .slice(0, 8);
  const reason = plan.recommendation_reason || "按你的时间、预算、距离和偏好综合排序。";

  const stops = useMemo(() => buildRouteStops(plan, request), [plan, request]);
  const transportInfo = TRANSPORT_INFO[request.transportation] || TRANSPORT_INFO.driving;

  return (
    <article className="plan-card">
      <div className="card-label">推荐方案</div>
      <p className="card-intro">我按你的需求整理了一个可执行方案，可以直接按下面的路线走。</p>
      <h2>{plan.title || "本地生活行程方案"}</h2>

      <div className="meta-grid">
        <MetaBox label="同行场景" value={companion} />
        <MetaBox label="主要意图" value={intent} />
        <MetaBox label="预计时长" value={getDurationText(plan.total_duration_minutes)} />
        <MetaBox label="匹配分" value={typeof plan.score === "number" ? plan.score.toFixed(1) : "待计算"} />
      </div>

      {stops.length > 0 && (
        <>
          <h3>行程路线</h3>
          <div className="route-section">
            {stops.map((stop, idx) => {
              const meta = STOP_TYPE_META[stop.type] || STOP_TYPE_META.activity;
              const isFirst = idx === 0;
              const isLast = idx === stops.length - 1;

              return (
                <div key={`${stop.name}-${idx}`} className="route-stop-group">
                  {/* 通勤连接线（第一个站点不显示） */}
                  {!isFirst && stop.commute && (
                    <div className="commute-connector">
                      <div className="commute-line" />
                      <div className="commute-info">
                        <span className="commute-icon">{transportInfo.icon}</span>
                        <span className="commute-label">{transportInfo.label}</span>
                        {stop.commute.travelMinutes && (
                          <span className="commute-time">约{stop.commute.travelMinutes}分钟</span>
                        )}
                      </div>
                      <div className="commute-line" />
                    </div>
                  )}

                  {/* 地点卡片 */}
                  <div className={`location-card ${isLast ? "location-card-last" : ""}`}>
                    <div className="location-card-header">
                      <span className="location-icon">{meta.icon}</span>
                      <div className="location-title-row">
                        <strong className="location-name">{stop.name}</strong>
                        <span className={`location-badge ${meta.badgeClass}`}>{meta.badge}</span>
                      </div>
                    </div>

                    <div className="location-card-body">
                      {/* 时间 */}
                      {stop.startTime && (
                        <div className="location-detail">
                          <span className="location-detail-icon">🕐</span>
                          <span>
                            {stop.startTime}
                            {stop.endTime && stop.endTime !== stop.startTime ? ` - ${stop.endTime}` : ""}
                          </span>
                        </div>
                      )}

                      {/* 地址 */}
                      {stop.locationDetail?.address && (
                        <div className="location-detail">
                          <span className="location-detail-icon">📌</span>
                          <span>
                            {stop.locationDetail.district
                              ? `${stop.locationDetail.district} `
                              : ""}
                            {stop.locationDetail.address || stop.location}
                          </span>
                        </div>
                      )}

                      {/* 标签行 */}
                      {(stop.cuisineType || stop.childFriendly || stop.needBooking || (stop.tags && stop.tags.length > 0)) && (
                        <div className="location-tags">
                          {stop.cuisineType && (
                            <em className="location-tag tag-cuisine">{stop.cuisineType}</em>
                          )}
                          {stop.childFriendly && (
                            <em className="location-tag tag-friendly">亲子友好</em>
                          )}
                          {stop.needBooking && (
                            <em className="location-tag tag-booking">需预约</em>
                          )}
                          {(stop.tags || []).slice(0, 2).map((tag) => (
                            <em key={tag} className="location-tag">{tag}</em>
                          ))}
                        </div>
                      )}

                      {/* 人均价格 */}
                      {stop.pricePerPerson > 0 && (
                        <div className="location-detail">
                          <span className="location-detail-icon">💰</span>
                          <span>人均 ¥{stop.pricePerPerson}</span>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {chips.length > 0 && (
        <div className="chips">
          {chips.map((chip) => (
            <span key={chip}>{label(chip)}</span>
          ))}
        </div>
      )}

      <p className="reason">{reason}</p>

      <div className="plan-actions">
        <button
          className="share-plan-btn"
          type="button"
          onClick={onShare}
          disabled={shareLoading}
        >
          {shareLoading ? (
            <>
              <span className="share-spinner" />
              生成分享卡片中
            </>
          ) : (
            <>
              <Share2 size={16} strokeWidth={2.2} />
              分享给朋友 / 转发家庭群
            </>
          )}
        </button>
      </div>

      <p className="mock-note">当前只生成方案和 Mock 执行结果，不会真实预约、支付或发消息。</p>
    </article>
  );
}

function ReceiptCard({ receipt, shareText, actions }) {
  const [copiedAction, setCopiedAction] = useState(null);

  function handleCopy(text, actionLabel) {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedAction(actionLabel);
      setTimeout(() => setCopiedAction(null), 2000);
    }).catch(() => {});
  }

  if (!receipt) return null;

  const summary = receipt.summary || {};
  const highlights = receipt.highlights || [];
  const status = receipt.status || {};

  return (
    <div className="receipt-card">
      <div className="receipt-header">
        <span className="receipt-icon">🧾</span>
        <div>
          <h3>{receipt.title || "行程小票"}</h3>
          <span className="receipt-subtitle">分享卡片 · 长按或点击下方按钮操作</span>
        </div>
      </div>

      {/* 摘要 */}
      <div className="receipt-summary">
        {summary.time && <div className="receipt-row"><span>⏰ 时间</span><strong>{summary.time}</strong></div>}
        {summary.group && <div className="receipt-row"><span>👥 同行</span><strong>{summary.group}</strong></div>}
        {summary.activity && <div className="receipt-row"><span>🎯 活动</span><strong>{summary.activity}</strong></div>}
        {summary.dining && <div className="receipt-row"><span>🍽️ 餐饮</span><strong>{summary.dining}</strong></div>}
        {summary.mobility && <div className="receipt-row"><span>🚗 交通</span><strong>{summary.mobility}</strong></div>}
        {summary.budget && <div className="receipt-row"><span>💰 预算</span><strong>{summary.budget}</strong></div>}
      </div>

      {/* 亮点 */}
      {highlights.length > 0 && (
        <div className="receipt-highlights">
          <h4>✨ 亮点</h4>
          {highlights.map((h, i) => (
            <div className="receipt-highlight-item" key={i}>{h}</div>
          ))}
        </div>
      )}

      {/* 状态 */}
      {Object.keys(status).length > 0 && (
        <div className="receipt-status">
          <h4>📋 备忘</h4>
          {Object.entries(status).map(([key, value]) => (
            <div className="receipt-status-item" key={key}>
              <span className="receipt-status-key">{key}</span>
              <span className="receipt-status-value">{value}</span>
            </div>
          ))}
        </div>
      )}

      {/* 分享语 */}
      {shareText && (
        <div className="receipt-share-text">
          <h4>💬 分享语</h4>
          <p>{shareText}</p>
          <button
            className="copy-share-btn"
            type="button"
            onClick={() => handleCopy(shareText, "copy")}
          >
            {copiedAction === "copy" ? (
              <><Check size={14} /> 已复制</>
            ) : (
              <><Copy size={14} /> 复制分享语</>
            )}
          </button>
        </div>
      )}

      {/* 分享操作 */}
      {actions && actions.length > 0 && (
        <div className="receipt-actions">
          {actions.map((act) => (
            <button
              key={act.action}
              className={`receipt-action-btn${act.action === "copy_text" ? " secondary" : ""}`}
              type="button"
              onClick={() => {
                if (act.action === "copy_text") {
                  handleCopy(act.text, act.label);
                }
              }}
            >
              {act.action === "share_to_wechat" && "💬 "}
              {act.action === "share_to_family_group" && "👨‍👩‍👧 "}
              {act.action === "copy_text" && (copiedAction === act.label ? <><Check size={14} /> 已复制</> : <><Copy size={14} /> {act.label}</>)}
              {act.action !== "copy_text" && act.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Composer({ value, setValue, onSubmit, disabled, onFocus }) {
  return (
    <form className="composer" onSubmit={onSubmit}>
      <input
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onFocus={onFocus}
        placeholder="消息"
        maxLength={300}
        disabled={disabled}
      />
      <button type="submit" aria-label="发送" disabled={disabled || !value.trim()}>
        <SendHorizontal size={22} strokeWidth={2.4} />
      </button>
    </form>
  );
}

// ==================== App ====================

export default function App() {
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef(null);

  // Structured input flow state
  const [step, setStep] = useState("idle"); // idle | collecting | followup | result
  const [guessLoading, setGuessLoading] = useState(false); // loading guess sentences inline
  const [slots, setSlots] = useState({
    companion_context: [],
    time_window: null,
    transportation: null,
    context_modifiers: [],
  });
  const [guessSentences, setGuessSentences] = useState([]); // [{text, slots: [{name, value}]}]
  const [accumulatedSlots, setAccumulatedSlots] = useState({}); // {slot_name: value}
  const [animatingSentence, setAnimatingSentence] = useState(null); // {text, startX, startY}
  const [receiptLoadingIdx, setReceiptLoadingIdx] = useState(null); // which message index is loading receipt
  const receiptCountRef = useRef(0);
  const [templateCards, setTemplateCards] = useState([]); // Round 1: 泛方案卡片
  const [templateCardsLoading, setTemplateCardsLoading] = useState(false);
  const [selectedCardId, setSelectedCardId] = useState(null); // user selected card id

  function resetChat() {
    setMessages([]);
    setDraft("");
    setError("");
    setStep("idle");
    setSlots({
      companion_context: [],
      time_window: null,
      transportation: null,
      context_modifiers: [],
    });
    setGuessSentences([]);
    setAccumulatedSlots({});
    setAnimatingSentence(null);
    setTemplateCards([]);
    setSelectedCardId(null);
  }

  // ---- Slot selection handlers ----

  function handleSlotSelect(category, value) {
    setSlots((prev) => {
      if (category === "companion_context") {
        const current = prev.companion_context || [];
        const isSelecting = !current.includes(value);
        if (isSelecting) {
          let next;
          if (value === "solo") {
            // "独自出行" 与除"带宠物"外的所有标签互斥
            next = [...current.filter((v) => v === "pet"), value];
          } else if (value === "pet") {
            next = [...current, value];
          } else {
            // 选择其他标签时取消"独自出行"
            next = [...current.filter((v) => v !== "solo"), value];
          }
          return { ...prev, companion_context: next };
        } else {
          return { ...prev, companion_context: current.filter((v) => v !== value) };
        }
      }
      if (category === "time_window") {
        // Single select — toggle off if same value clicked again
        return { ...prev, time_window: prev.time_window === value ? null : value };
      }
      if (category === "transportation") {
        const nextTransport = prev.transportation === value ? null : value;
        const mods = nextTransport ? TRANSPORT_MODIFIERS[nextTransport] || [] : [];
        return {
          ...prev,
          transportation: nextTransport,
          context_modifiers: mods,
        };
      }
      return prev;
    });
  }

  async function handleSlotsSubmit() {
    setStep("followup");
    setGuessLoading(true);
    setError("");

    try {
      const response = await fetch("/api/suggest-followup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          companion_context: slots.companion_context,
          time_window: slots.time_window,
          transportation: slots.transportation,
          context_modifiers: slots.context_modifiers,
        }),
      });

      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || "请求失败");
      }

      const data = await response.json();
      setGuessSentences(data.sentences || []);
      setAccumulatedSlots({});
    } catch (err) {
      setError(err instanceof Error ? err.message : "追问生成失败");
      setStep("collecting");
    } finally {
      setGuessLoading(false);
    }
  }

  function handleGuessSentenceClick(sentence, event) {
    if (animatingSentence) return;

    const rect = event.currentTarget.getBoundingClientRect();
    const phoneFrame = event.currentTarget.closest(".phone-frame");
    const phoneRect = phoneFrame?.getBoundingClientRect() || { left: 0, top: 0 };

    setAnimatingSentence({
      text: sentence.text,
      startX: rect.left - phoneRect.left,
      startY: rect.top - phoneRect.top,
      startWidth: rect.width,
      startHeight: rect.height,
    });

    // Accumulate slots from clicked sentence
    if (sentence.slots) {
      setAccumulatedSlots((prev) => {
        const next = { ...prev };
        for (const slot of sentence.slots) {
          next[slot.name] = slot.value;
        }
        return next;
      });
    }

    // After animation: append to draft, remove sentence (不立即拉卡片，等用户发送)
    setTimeout(() => {
      setDraft((prev) => (prev ? prev + "。" + sentence.text : sentence.text));
      setGuessSentences((prev) => prev.filter((s) => s.text !== sentence.text));
      setAnimatingSentence(null);
    }, 420);
  }

  async function fetchTemplateCards(composedMessage) {
    setTemplateCardsLoading(true);
    setError("");
    const groupType = (slots.companion_context || [])[0] || "";

    try {
      const response = await fetch("/api/template-cards", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          group_type: groupType,
          time_window: slots.time_window || undefined,
          transportation: slots.transportation || undefined,
          user_modifications: accumulatedSlots,
          additional_query: composedMessage || undefined,
        }),
      });

      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || "泛方案卡片加载失败");
      }

      const data = await response.json();
      const cards = data?.data?.cards || [];
      if (cards.length > 0) {
        setTemplateCards(cards);
        setStep("templates");
        setSelectedCardId(null);
      } else {
        // 跳步：用户信息足够丰富，直接生成方案
        setStep("result");
        setTemplateCards([]);
        submitWithCard(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "泛方案加载失败");
    } finally {
      setTemplateCardsLoading(false);
    }
  }

  async function handleCardSelect(cardId) {
    if (loading || !cardId) return;
    setSelectedCardId(cardId);
    // 给用户短暂视觉反馈后触发方案生成
    setTimeout(() => submitWithCard(cardId), 300);
  }

  async function submitWithCard(cardId) {
    setLoading(true);
    setStep("result");
    setTemplateCards([]);
    setGuessSentences([]);
    setError("");

    const groupType = (slots.companion_context || [])[0] || "";
    const currentSlots = {
      group_type: groupType === "family_with_children" ? "家庭出行" :
                   groupType === "family_with_elderly" ? "家庭出行" :
                   groupType === "friends" ? "朋友聚会" :
                   groupType === "colleagues" ? "朋友聚会" :
                   groupType === "couple" ? "情侣约会" :
                   groupType === "solo" ? "独自一人" : "独自一人",
      time_slot: slots.time_window || "",
      mobility: {
        driving: "自驾", transit: "公共交通", taxi: "打车", bike_walk: "骑行/步行",
      }[slots.transportation] || "",
      ...accumulatedSlots,
    };

    const message = draft.trim();
    if (message) {
      setMessages((prev) => [...prev, { role: "user", content: message }]);
    }
    setDraft("");

    let lockedConstraints = {};

    // Round 2: 如果有 cardId，先调用 /api/select-card 锁定约束
    if (cardId) {
      try {
        const selectRes = await fetch("/api/select-card", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            card_id: cardId,
            group_type: groupType,
            current_slots: currentSlots,
            user_additional_input: message || undefined,
          }),
        });

        if (selectRes.ok) {
          const selectData = await selectRes.json();
          lockedConstraints = selectData?.data?.locked_constraints || {};
        }
      } catch {
        // select-card 失败不阻塞，继续用已有槽位生成方案
      }
    } else {
      // 没选卡片（跳步场景），直接用已有槽位
      lockedConstraints = currentSlots;
    }

    // Round 3: 调用 /api/chat 生成具体方案
    try {
      const chatRes = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: message || "",
          locked_constraints: lockedConstraints,
        }),
      });

      if (!chatRes.ok) {
        const detail = await chatRes.text();
        throw new Error(detail || "方案生成失败");
      }

      const result = await chatRes.json();
      setMessages((prev) => [...prev, { role: "agent", result }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "方案生成失败");
    } finally {
      setLoading(false);
      setSelectedCardId(null);
    }
  }

  async function handleFollowupSend(text) {
    const message = text.trim();
    if (!message || loading) return;

    setDraft("");
    setError("");
    setGuessSentences([]);
    setMessages((prev) => [...prev, { role: "user", content: message }]);

    // 用户发送小猜问编辑后的文本 → 拉取泛方案卡片（Round 1）
    fetchTemplateCards(message);
  }

  // ---- Free-text send (fallback / existing path) ----

  async function sendMessage(text) {
    const message = text.trim();
    if (!message || loading) return;

    setDraft("");
    setError("");
    setLoading(true);
    setStep("result"); // skip structured flow
    setMessages((prev) => [...prev, { role: "user", content: message }]);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });

      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || "请求失败");
      }

      const result = await response.json();
      setMessages((prev) => [...prev, { role: "agent", result }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "请求失败");
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(event) {
    event.preventDefault();
    if (step === "templates") {
      // 用户在泛方案卡片阶段直接发送文字：跳过卡片选择，直接用文字生成方案
      submitWithCard(null);
    } else if (step === "followup") {
      handleFollowupSend(draft);
    } else {
      sendMessage(draft);
    }
  }

  async function handleShare(msgIndex, result) {
    if (receiptLoadingIdx !== null) return;

    const planId = result?.plan_id || result?.best_plan?.plan_id || "";
    const bestPlan = result?.best_plan || {};
    const lockedConstraints = result?.request || {};

    setReceiptLoadingIdx(msgIndex);

    try {
      const response = await fetch("/api/receipt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plan_id: planId,
          plan_data: bestPlan,
          locked_constraints: lockedConstraints,
        }),
      });

      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || "小票生成失败");
      }

      const receiptResult = await response.json();
      const receiptData = receiptResult?.data || receiptResult;

      setMessages((prev) => {
        const next = [...prev];
        if (next[msgIndex] && next[msgIndex].role === "agent") {
          next[msgIndex] = {
            ...next[msgIndex],
            receipt: receiptData,
          };
        }
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "小票生成失败");
    } finally {
      setReceiptLoadingIdx(null);
    }
  }

  function handleComposerFocus() {
    if (step === "idle") {
      setStep("collecting");
    }
  }

  function handleGuessCardPick(prompt) {
    setDraft(prompt);
    setStep("collecting");
  }

  // Auto-scroll to receipt card when it appears
  useEffect(() => {
    const receiptCount = messages.filter((m) => m.role === "agent" && m.receipt).length;
    if (receiptCount > receiptCountRef.current) {
      receiptCountRef.current = receiptCount;
      // Wait for DOM update, then scroll the receipt into view
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          const receiptEl = document.querySelector(".receipt-card");
          if (receiptEl) {
            receiptEl.scrollIntoView({ behavior: "smooth", block: "start" });
          }
        });
      });
    }
  }, [messages]);

  // ---- Render ----

  return (
    <main className="app-shell">
      <section className="phone-frame">
        <StatusBar />
        <Header onReset={resetChat} />
        <div className="chat-scroll" ref={scrollRef}>
          {step === "idle" && messages.length === 0 && (
            <EmptyState onPick={handleGuessCardPick} />
          )}

          {step === "collecting" && (
            <StructuredPanel
              slots={slots}
              onSlotSelect={handleSlotSelect}
              onSubmit={handleSlotsSubmit}
              disabled={loading}
            />
          )}

          {(step === "followup" || step === "templates" || step === "result") && (
            <Q1Summary slots={slots} />
          )}

          {step === "followup" && !guessLoading && (
            <GuessSentences
              sentences={guessSentences}
              onSentenceClick={handleGuessSentenceClick}
              disabled={loading}
              animatingSentence={animatingSentence}
            />
          )}

          {step === "followup" && guessLoading && (
            <div className="guess-loading">
              <span className="guess-loading-dot" />
              <span className="guess-loading-dot" />
              <span className="guess-loading-dot" />
              <p>小团正在猜你的偏好</p>
            </div>
          )}

          {error && step !== "collecting" && <div className="error-card">{error}</div>}

          {messages.map((message, index) =>
            message.role === "user" ? (
              <UserBubble key={`${message.role}-${index}`} content={message.content} />
            ) : (
              <div key={`${message.role}-${index}`}>
                <PlanCard
                  result={message.result}
                  onShare={() => handleShare(index, message.result)}
                  shareLoading={receiptLoadingIdx === index}
                />
                {message.receipt && (
                  <ReceiptCard
                    receipt={message.receipt.receipt}
                    shareText={message.receipt.share_text}
                    actions={message.receipt.actions}
                  />
                )}
              </div>
            ),
          )}

          {step === "templates" && (
            <TemplateCards
              cards={templateCards}
              onSelect={handleCardSelect}
              loading={templateCardsLoading}
              selectedId={selectedCardId}
            />
          )}

          {loading && (step === "result" || step === "followup") && <LoadingCard />}
        </div>
        <FlyingSentence animatingSentence={animatingSentence} />
        <Composer
          value={draft}
          setValue={setDraft}
          onSubmit={handleSubmit}
          disabled={loading}
          onFocus={handleComposerFocus}
        />
      </section>
    </main>
  );
}
