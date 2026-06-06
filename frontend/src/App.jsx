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
    prompt: "想在上海世纪公园看绣球花，拍拍照，附近吃个饭，轻松半天",
    locked_location: "世纪公园",
    location_hint: "世纪公园绣球花，适合拍照散步，附近有餐厅",
    guessFlow: {
      context_modifiers: ["outdoor_walk", "photo_spot", "weather_dependent"],
      implied_constraints: {
        activity_preference: "outdoor",
        context_modifiers: ["photo_spot", "weather_dependent", "low_energy", "near_subway"],
        must_include_location: "世纪公园",
        guaranteed_activities: [
          {
            name: "世纪公园绣球花径",
            type: "park",
            location_hint: "世纪公园",
            description: "绣球花开得正盛，这周末是花期尾巴，适合拍照散步",
            tags: ["公园", "绣球花", "拍照打卡", "户外散心"],
            duration_minutes: 120,
            poi_category: "户外.公园",
          },
        ],
        // 世纪公园卡片未 showcase 具体餐馆，"旁边吃饭也方便"由正常搜索覆盖，不加 guaranteed_restaurants
      },
    },
  },
  {
    primaryIntent: "meal",
    title: "🍽️ 犒劳自己，吃顿好的",
    prefix: "武康路新开了一家",
    highlight: "黑珍珠粤菜馆",
    suffix: "，上个月刚上榜，趁现在还没太火可以先去。人均200左右，周末值得。",
    chips: ["吃顿好的", "新上榜", "适合约饭"],
    prompt: "想在武康路附近找一家不错的餐厅，人均200左右，适合周末慢慢吃",
    locked_location: "武康路",
    location_hint: "武康路，黑珍珠粤菜馆，人均200，附近可逛",
    guessFlow: {
      context_modifiers: ["meal", "high_budget", "place_quality"],
      implied_constraints: {
        primary_intent_override: "meal",
        budget_level: "high",
        context_modifiers: ["high_budget", "place_quality", "quiet"],
        must_include_location: "武康路",
        guaranteed_restaurants: [
          {
            name: "黑珍珠粤菜馆",
            cuisine_type: "粤菜",
            location_hint: "武康路",
            description: "新开的黑珍珠上榜粤菜馆，人均200左右，环境讲究适合慢慢吃",
            tags: ["黑珍珠", "粤菜", "高级", "安静", "新开"],
            budget_level: "high",
          },
        ],
      },
    },
  },
  {
    primaryIntent: "culture_experience",
    title: "🎨 看展逛逛，随便晃晃",
    prefix: "上生·新所开了",
    highlight: "「路易斯·韦恩」猫猫插画展",
    suffix: "，展不大但很出片，逛完旁边就是番禺路咖啡街，适合放松。",
    chips: ["看展", "低体力", "咖啡顺路"],
    prompt: "想去上生·新所看猫猫插画展，逛完在番禺路喝杯咖啡，轻松一下午",
    locked_location: "上生·新所",
    location_hint: "上生·新所猫猫插画展，旁边番禺路咖啡街，低体力适合拍照",
    guessFlow: {
      context_modifiers: ["culture_experience", "photo_spot", "low_energy", "cafe_tea"],
      implied_constraints: {
        activity_preference: "indoor",
        context_modifiers: ["photo_spot", "low_energy", "quiet", "cafe_tea", "no_reservation"],
        must_include_location: "上生·新所",
        guaranteed_activities: [
          {
            name: "路易斯·韦恩猫猫插画展",
            type: "exhibition",
            location_hint: "上生·新所",
            description: "展不大但很出片，适合轻松逛展拍照",
            tags: ["展览", "插画", "猫", "拍照打卡", "文艺"],
            duration_minutes: 90,
            poi_category: "文化.展览",
          },
        ],
        guaranteed_restaurants: [
          {
            name: "番禺路咖啡馆",
            cuisine_type: "咖啡",
            location_hint: "番禺路",
            description: "番禺路咖啡街，逛完展喝杯咖啡放松",
            tags: ["咖啡", "文艺", "安静", "番禺路"],
            budget_level: "medium",
          },
        ],
      },
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
  if (!value || value === "unknown") return "待确认";
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

// 推荐信息内容类型 → 中文标签
const CONTENT_TYPE_LABEL = {
  sub: "🎮 子设施",
  event: "🎪 限时活动",
  coupon: "🎫 优惠",
  dining: "🍜 附近美食",
  dish: "🥘 推荐菜",
};

/**
 * 从 timeline / route_infos 中构建展示用的行程站点列表。
 * 每个站点包含：名称、地点、时间、标签、到达该站的通勤信息。
 */
function buildRouteStops(plan, request) {
  const timeline = plan.timeline || [];
  const activities = plan.activities || [];
  const restaurant = plan.restaurant;
  const dinnerRestaurant = plan.dinner_restaurant;
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

  // 构建 route_infos 的 O(1) 查找表，避免每个站点重复 .find() 扫描
  const routeByTo = new Map();
  for (const r of routeInfos) {
    if (r.to) routeByTo.set(r.to, r);
  }

  const stops = rawStops.map((item, stopIndex) => {
    const isActivity = item.type === "activity";
    const isMeal = item.type === "meal";
    const [startTime, endTime] = (item.time || "").split("-");

    // 匹配活动/餐厅的富数据
    let enriched = {};
    let matchedRestaurant = null;  // 提升作用域，供 return 中的 name 使用
    if (isActivity) {
      // 精确匹配优先，避免"来福士广场"匹配到"上海来福士广场"
      const matched = activities.find((a) => item.activity === a.name)
        || activities.find((a) => item.activity.includes(a.name) || a.name.includes(item.activity));
      if (matched) {
        enriched = {
          tags: matched.tags || [],
          childFriendly: matched.child_friendly,
          needBooking: matched.need_booking,
          locationDetail: matched.location,
          durationMinutes: matched.duration_minutes,
          pricePerPerson: matched.price_per_person,
          recommendations: matched.recommendations || [],
        };
      }
    } else if (isMeal) {
      // 匹配午餐或晚餐餐厅：按"午餐"/"晚餐"关键词精准路由
      const isLunch = item.activity.includes("午餐");
      const isDinner = item.activity.includes("晚餐");

      if (isLunch && restaurant) {
        matchedRestaurant = restaurant;
      } else if (isDinner && dinnerRestaurant) {
        matchedRestaurant = dinnerRestaurant;
      } else if (restaurant && (item.activity.includes(restaurant.name) || (restaurant.location?.name && item.location === restaurant.location.name))) {
        // 兜底：非午/晚餐的用餐（如"用餐"标记），用主餐厅
        matchedRestaurant = restaurant;
      }
      if (matchedRestaurant) {
        enriched = {
          cuisineType: matchedRestaurant.cuisine_type,
          locationDetail: matchedRestaurant.location,
          pricePerPerson: matchedRestaurant.price_per_person,
          tags: [],
          recommendations: matchedRestaurant.recommendations || [],
        };
      }
    }

    // 通勤信息：第一个站点无 commute，后续站点从 route_infos 中匹配
    let commute = null;
    if (stopIndex > 0 && routeInfos.length > 0) {
      // route_infos 结构: [home→act1, act1→act2?, last_act→restaurant, restaurant→home]
      // 站点间通勤对应 route_infos 的第 stopIndex 项（当只有一个活动时）
      // 从 route_infos 查找表中 O(1) 匹配本站 location
      let route = routeByTo.get(item.location);
      if (!route && item.location) {
        // 宽松匹配：location 包含 route key
        for (const [to, r] of routeByTo) {
          if (item.location.includes(to)) { route = r; break; }
        }
      }
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
      name: isMeal && matchedRestaurant ? matchedRestaurant.name : (isMeal && restaurant ? restaurant.name : item.activity),
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

function Header({ onReset, onBack, canGoBack }) {
  return (
    <header className="phone-header">
      <button
        className="icon-button"
        type="button"
        aria-label="返回"
        onClick={canGoBack ? onBack : undefined}
        style={{ opacity: canGoBack ? 1 : 0.3, cursor: canGoBack ? "pointer" : "default" }}
      >
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
            onClick={() => onPick(card)}
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

function StructuredPanel({ slots, onSlotSelect, onSubmit, disabled, toastVisible, toastKey }) {
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
        {toastVisible && (
          <div className="slot-toast" key={toastKey}>请先选择出行人</div>
        )}
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

const TIME_WINDOW_DURATION = {
  morning: "约3-4小时",
  afternoon: "约4-5小时",
  evening: "约2-3小时",
  full_day: "约6-8小时",
  night: "约2-3小时",
  now: "约2-3小时",
};

function LoadingCard({ slots, accumulatedSlots, guessCardCtx }) {
  const compContext = (slots?.companion_context || []).filter(c => c && c !== "unknown");
  const companion = compContext.length > 0
    ? compContext.map(c => LABELS[c] || c).join("、")
    : "分析中…";

  const primaryIntent = accumulatedSlots?.primary_intent || guessCardCtx?.primaryIntent;
  const intent = primaryIntent ? (LABELS[primaryIntent] || primaryIntent) : "分析中…";

  const duration = TIME_WINDOW_DURATION[slots?.time_window] || "约3-4小时";

  return (
    <div className="plan-card loading-card">
      <div className="card-label">正在根据你的偏好规划方案</div>
      <div className="meta-grid">
        <MetaBox label="同行场景" value={companion} />
        <MetaBox label="主要意图" value={intent} />
        <MetaBox label="预计时长" value={duration} />
        <MetaBox label="匹配分" value="计算中…" />
      </div>
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
  const [selectedRecs, setSelectedRecs] = useState({});
  const [orderPlaced, setOrderPlaced] = useState(false);
  const [orderSummary, setOrderSummary] = useState(null); // {count, total}
  const [showConfetti, setShowConfetti] = useState(false);

  // 计算选中项总价
  const selectedEntries = Object.entries(selectedRecs);
  const selectedCount = selectedEntries.length;
  const totalSelectedPrice = selectedEntries.reduce((sum, [, rec]) => sum + (rec.price || 0), 0);

  // 浮动价签：底部合计栏不可见时出现，约束在 phone-frame 内
  const totalBarRef = useRef(null);
  const pillRef = useRef(null);
  const [pillVisible, setPillVisible] = useState(false);
  // lazy 初始化：直接算好右下角位置
  const [pillPos, setPillPos] = useState(() => {
    const frame = document.querySelector(".phone-frame");
    if (frame) {
      const r = frame.getBoundingClientRect();
      return { x: r.right - 124, y: r.top + 220 };
    }
    return { x: window.innerWidth - 124, y: 240 };
  });
  const [pillSide, setPillSide] = useState("right");
  const dragRef = useRef({ dragging: false, startX: 0, startY: 0, startPillX: 0, startPillY: 0 });

  // 价签出现时重新校准位置
  useEffect(() => {
    if (!pillVisible) return;
    const frame = document.querySelector(".phone-frame");
    if (frame) {
      const r = frame.getBoundingClientRect();
      setPillPos(prev => ({
        x: pillSide === "left" ? r.left + 4 : r.right - 124,
        y: Math.max(r.top + 50, Math.min(prev.y, r.bottom - 80)),
      }));
    }
  }, [pillVisible, pillSide]);

  function getPhoneBounds() {
    const frame = document.querySelector(".phone-frame");
    if (!frame) return { left: 0, right: window.innerWidth, top: 0, bottom: window.innerHeight };
    return frame.getBoundingClientRect();
  }

  useEffect(() => {
    if (selectedCount === 0) { setPillVisible(false); return; }
    // 只要选中了项目就立即显示浮动价签
    setPillVisible(true);

    const el = totalBarRef.current;
    const root = document.querySelector(".chat-scroll");
    if (!el || !root) return; // ref 未就绪或找不到滚动容器则保持显示

    function check() {
      const rootRect = root.getBoundingClientRect();
      const elRect = el.getBoundingClientRect();
      // 合计栏完全在滚动容器可视区内 → 隐藏浮动价签；否则显示
      const visible = elRect.bottom <= rootRect.bottom - 70 && elRect.top >= rootRect.top;
      setPillVisible(!visible);
    }

    root.addEventListener("scroll", check, { passive: true });
    check(); // 初始检查：如果合计栏当前可见则立即隐藏
    return () => root.removeEventListener("scroll", check);
  }, [selectedCount, totalSelectedPrice]);

  function handlePillPointerDown(e) {
    e.preventDefault();
    const pt = e.touches ? e.touches[0] : e;
    dragRef.current = {
      dragging: true,
      startX: pt.clientX, startY: pt.clientY,
      startPillX: pillPos.x, startPillY: pillPos.y,
    };
  }

  useEffect(() => {
    function onMove(e) {
      if (!dragRef.current.dragging) return;
      const pt = e.touches ? e.touches[0] : e;
      const bounds = getPhoneBounds();
      const dx = pt.clientX - dragRef.current.startX;
      const dy = pt.clientY - dragRef.current.startY;
      const pillW = 120;
      setPillPos({
        x: Math.max(bounds.left + 4, Math.min(bounds.right - pillW - 4, dragRef.current.startPillX + dx)),
        y: Math.max(bounds.top + 50, Math.min(bounds.bottom - 70, dragRef.current.startPillY + dy)),
      });
    }
    function onUp() {
      if (!dragRef.current.dragging) return;
      dragRef.current.dragging = false;
      const bounds = getPhoneBounds();
      const pillW = 120;
      // 吸附到手机框最近边
      setPillPos(prev => {
        const mid = (bounds.left + bounds.right) / 2;
        const side = prev.x < mid ? "left" : "right";
        setPillSide(side);
        return { x: side === "left" ? bounds.left + 4 : bounds.right - pillW - 4, y: prev.y };
      });
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    window.addEventListener("touchmove", onMove, { passive: false });
    window.addEventListener("touchend", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      window.removeEventListener("touchmove", onMove);
      window.removeEventListener("touchend", onUp);
    };
  }, []);
  const creativeTitle = result?.creative_title || "";
  const originalTitle = plan.title || "";
  const stops = useMemo(() => buildRouteStops(plan, request), [plan, request]);
  const transportInfo = TRANSPORT_INFO[request.transportation] || TRANSPORT_INFO.driving;

  return (
    <article className="plan-card">
      <h2 className="creative-title">{creativeTitle || originalTitle || "本地生活行程方案"}</h2>
      {creativeTitle && originalTitle && (
        <p className="original-title-sub">{originalTitle}</p>
      )}

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

                      {/* 推荐信息横排（子设施/活动/优惠券/附近餐饮/推荐菜） */}
                      {stop.recommendations && stop.recommendations.length > 0 && (
                        <div className="rec-row">
                          {stop.recommendations.map((rec, recIdx) => {
                            const recKey = `${idx}-${recIdx}`;
                            const isSelected = !!selectedRecs[recKey];
                            return (
                              <div
                                key={recIdx}
                                className={`rec-item ${isSelected ? "rec-item-selected" : ""}`}
                                onClick={() => {
                                  setSelectedRecs(prev => {
                                    const next = { ...prev };
                                    if (next[recKey]) {
                                      delete next[recKey];
                                    } else {
                                      next[recKey] = rec;
                                    }
                                    return next;
                                  });
                                }}
                              >
                                {rec.badge && (
                                  <span className={`rec-badge rec-badge-${rec.content_type}`}>
                                    {rec.badge}
                                  </span>
                                )}
                                <div className="rec-header">
                                  <span className="rec-type">{CONTENT_TYPE_LABEL[rec.content_type] || "✨ 推荐"}</span>
                                  {rec.price > 0 && (
                                    <span className="rec-price">¥{rec.price}</span>
                                  )}
                                </div>
                                <span className="rec-name">{rec.name}</span>
                                {rec.highlight && (
                                  <span className="rec-highlight">{rec.highlight}</span>
                                )}
                              </div>
                            );
                          })}
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

      {/* 选中推荐项合计栏 */}
      {totalSelectedPrice > 0 && (
        <div className="rec-total-bar" ref={totalBarRef}>
          <span className="rec-total-label">已选 {selectedCount} 项</span>
          <span className="rec-total-price">合计 ¥{totalSelectedPrice}</span>
          <button
            className="rec-order-btn"
            type="button"
            onClick={() => {
              const summary = { count: selectedCount, total: totalSelectedPrice };
              setOrderSummary(summary);
              setOrderPlaced(true);
              setSelectedRecs({});
              setShowConfetti(true);
              setTimeout(() => setShowConfetti(false), 2800);
            }}
          >
            一键下单
          </button>
        </div>
      )}

      {/* 下单成功状态栏 */}
      {orderPlaced && orderSummary && (
        <div className="order-success-bar">
          <span className="order-success-emoji">🎉</span>
          <div className="order-success-text">
            <strong>下单成功</strong>
            <span>{orderSummary.count} 项服务已预约 · 合计 ¥{orderSummary.total}</span>
          </div>
          <button
            className="order-success-dismiss"
            type="button"
            onClick={() => setOrderPlaced(false)}
          >
            ✕
          </button>
        </div>
      )}

      {/* 浮动窄价签：底部合计栏不可见时悬浮在屏幕上 */}
      {pillVisible && (
        <div
          className="rec-float-pill-container"
          style={{ left: pillPos.x, top: pillPos.y }}
          onMouseDown={handlePillPointerDown}
          onTouchStart={handlePillPointerDown}
        >
          <div className="rec-float-roo-wrap">
            <img src="/kangaroo.png" alt="" className="rec-float-roo" />
          </div>
          <div className="rec-float-pill-body">
            <span className="rec-float-count">{selectedCount}项</span>
            <span className="rec-float-price">¥{totalSelectedPrice}</span>
          </div>
        </div>
      )}

      {/* 礼花动效：固定定位覆盖手机框可视区域，跟随滚动位置 */}
      {showConfetti && (() => {
        const frame = document.querySelector(".phone-frame");
        const fRect = frame ? frame.getBoundingClientRect() : null;
        const overlayStyle = fRect ? {
          position: "fixed",
          left: fRect.left,
          top: fRect.top + 46 + 82,  // status bar + header
          width: fRect.width,
          height: fRect.height - 46 - 82 - 94, // minus status, header, composer
          zIndex: 150,
          pointerEvents: "none",
          overflow: "hidden",
          borderRadius: "0 0 32px 32px",
        } : {};
        return (
          <div style={overlayStyle}>
            {Array.from({ length: 50 }).map((_, i) => (
              <span
                key={i}
                className={`confetti-piece confetti-${i % 6}`}
                style={{
                  position: "absolute",
                  top: "-10px",
                  left: `${Math.random() * 100}%`,
                  animationDelay: `${Math.random() * 0.8}s`,
                  animationDuration: `${1.6 + Math.random() * 1.4}s`,
                }}
              />
            ))}
          </div>
        );
      })()}

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

function ReceiptCard({ receipt, shareText, actions, onClose }) {
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
      {/* 关闭按钮 */}
      {onClose && (
        <button className="receipt-close-btn" type="button" onClick={onClose} aria-label="关闭">
          ✕
        </button>
      )}

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
        </div>
      )}

      {/* 分享操作 */}
      {actions && actions.length > 0 && (
        <div className="receipt-actions">
          {actions.map((act) => (
            <button
              key={act.action}
              className={`receipt-action-btn${act.action === "copy_link" ? " secondary" : ""}`}
              type="button"
              onClick={() => {
                if (act.action === "copy_link" || act.action === "copy_text") {
                  handleCopy(act.text, act.label);
                }
              }}
            >
              {act.action === "share_to_wechat" && "💬 "}
              {act.action === "copy_link" && (copiedAction === act.label ? <><Check size={14} /> 已复制</> : <><Copy size={14} /> {act.label}</>)}
              {(act.action !== "copy_link" && act.action !== "copy_text") && act.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ReceiptOverlay({ data, onClose }) {
  if (!data) return null;

  return (
    <div className="receipt-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="receipt-overlay-inner">
        <ReceiptCard
          receipt={data.receipt}
          shareText={data.shareText}
          actions={data.actions}
          onClose={onClose}
        />
      </div>
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
  const [stepHistory, setStepHistory] = useState([]); // navigation stack for back button
  const [messageSnapshots, setMessageSnapshots] = useState([]); // message count snapshots per step
  const messagesLenRef = useRef(0); // synced with messages.length for snapshot capture
  const [receiptOverlay, setReceiptOverlay] = useState(null); // overlay receipt data
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
  const [templateCards, setTemplateCards] = useState([]); // Round 1: 泛方案卡片
  const [petToastCount, setPetToastCount] = useState(0);
  const [toastVisible, setToastVisible] = useState(false);
  const toastTimerRef = useRef(null);

  // 宠物标签 toast：每次 petToastCount 变化时显示，2.5s 后自动消失
  useEffect(() => {
    if (petToastCount > 0) {
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
      setToastVisible(true);
      toastTimerRef.current = setTimeout(() => setToastVisible(false), 2500);
    }
  }, [petToastCount]);

  const [templateCardsLoading, setTemplateCardsLoading] = useState(false);
  const [selectedCardId, setSelectedCardId] = useState(null); // user selected card id
  const [guessCardCtx, setGuessCardCtx] = useState(null); // GUESS_CARD picked for direct flow (skips input box & template cards)

  // 同步 messages 长度到 ref，供 goToStep 快照使用
  useEffect(() => {
    messagesLenRef.current = messages.length;
  }, [messages]);

  function goToStep(newStep) {
    setStep((prev) => {
      if (prev !== newStep && prev !== "idle") {
        setStepHistory((h) => [...h, prev]);
        setMessageSnapshots((s) => [...s, messagesLenRef.current]);
      }
      return newStep;
    });
  }

  function handleBack() {
    setStepHistory((prev) => {
      if (prev.length === 0) return prev;
      const next = [...prev];
      const lastStep = next.pop();
      setStep(lastStep);
      setDraft("");

      // 按快照回退消息：弹出当前 step 的快照，恢复到上一步的消息数量
      setMessageSnapshots((snaps) => {
        const nextSnaps = [...snaps];
        const targetLen = nextSnaps.pop() || 0;
        setMessages((m) => m.slice(0, targetLen));
        return nextSnaps;
      });

      // 清理步骤相关状态
      if (lastStep === "collecting") {
        setGuessSentences([]);
        setAccumulatedSlots({});
        setTemplateCards([]);
        setSelectedCardId(null);
      } else if (lastStep === "followup") {
        setTemplateCards([]);
        setSelectedCardId(null);
      } else if (lastStep === "templates") {
        setSelectedCardId(null);
      }
      return next;
    });
  }

  function resetChat() {
    setMessages([]);
    setDraft("");
    setError("");
    setStep("idle");
    setStepHistory([]);
    setMessageSnapshots([]);
    setReceiptOverlay(null);
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
    setGuessCardCtx(null);
  }

  // ---- Slot selection handlers ----

  function handleSlotSelect(category, value) {
    // 带宠物不可单独选择，需先选出行人
    if (category === "companion_context" && value === "pet") {
      const current = slots.companion_context || [];
      const hasSelection = current.some(v => v !== "pet");
      const isSelecting = !current.includes("pet");
      if (isSelecting && !hasSelection) {
        setPetToastCount(c => c + 1);
        return;
      }
    }

    setSlots((prev) => {
      if (category === "companion_context") {
        const current = prev.companion_context || [];
        const isSelecting = !current.includes(value);
        if (isSelecting) {
          let next;
          if (value === "solo" || value === "couple") {
            // "独自出行" 和 "情侣出行" 与除"带宠物"外的所有标签互斥
            next = [...current.filter((v) => v === "pet"), value];
          } else if (value === "pet") {
            // 带宠物不能单独选，必须依附于已有同行人类型
            const nonPet = current.filter(v => v !== "pet");
            if (nonPet.length === 0) return prev;
            next = [...current, value];
          } else {
            // 选择其他标签时取消"独自出行"和"情侣出行"
            next = [...current.filter((v) => v !== "solo" && v !== "couple"), value];
          }
          if (next.length > 3) return prev;
          return { ...prev, companion_context: next };
        } else {
          let filtered = current.filter((v) => v !== value);
          // 取消选择后如果只剩下"带宠物"，连带取消
          if (filtered.length === 1 && filtered[0] === "pet") filtered = [];
          return { ...prev, companion_context: filtered };
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
    goToStep("followup");
    setGuessLoading(true);
    setError("");

    try {
      const body = {
        companion_context: slots.companion_context,
        time_window: slots.time_window,
        transportation: slots.transportation,
        context_modifiers: [...(slots.context_modifiers || []), ...(guessCardCtx?.guessFlow?.context_modifiers || [])],
      };

      // GUESS_CARD 路径：传递地点上下文，让小猜问围绕卡片地点展开
      if (guessCardCtx) {
        body.location_hint = guessCardCtx.location_hint || "";
        body.locked_location = guessCardCtx.locked_location || "";
        body.primary_intent = guessCardCtx.primaryIntent || "";
      }

      const response = await fetch("/api/suggest-followup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
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
      goToStep("collecting");
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
        goToStep("templates");
        setSelectedCardId(null);
      } else {
        // 跳步：用户信息足够丰富，直接生成方案
        goToStep("result");
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
    goToStep("result");
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

  // GUESS_CARD 快捷路径：跳过泛方案卡片，用卡片约束 + 小猜问补充槽位直接生成方案
  async function submitGuessCardPlan(message) {
    const card = guessCardCtx;
    if (!card) return;
    const gf = card.guessFlow || {};

    const groupType = (slots.companion_context || [])[0] || "";
    const currentSlots = {
      group_type: groupType === "family_with_children" ? "家庭出行" :
                   groupType === "family_with_elderly" ? "家庭出行" :
                   groupType === "friends" ? "朋友聚会" :
                   groupType === "colleagues" ? "朋友聚会" :
                   groupType === "couple" ? "情侣约会" :
                   groupType === "solo" ? "独自一人" : "",
      time_slot: slots.time_window || "",
      mobility: {
        driving: "自驾", transit: "公共交通", taxi: "打车", bike_walk: "骑行/步行",
      }[slots.transportation] || "",
      primary_intent: card.primaryIntent,
      context_modifiers: [
        ...(gf.implied_constraints?.context_modifiers || []),
        ...(slots.context_modifiers || []),
        ...(gf.context_modifiers || []),
      ],
      ...gf.implied_constraints,
      ...accumulatedSlots,
    };

    // 合并卡片约束和小猜问补充槽位
    const lockedConstraints = { ...currentSlots };

    // 锁定地点：确保最终方案包含 GUESS_CARD 提到的具体地点
    if (card.locked_location) {
      lockedConstraints.must_include_location = card.locked_location;
    }

    // 构建消息：前缀锁定地点，后缀为用户小猜问补充内容
    const baseMsg = card.locked_location
      ? `去${card.locked_location}，${card.prompt}`
      : (card.prompt || "");
    const fullMessage = message ? `${baseMsg}。${message}` : baseMsg;

    try {
      const chatRes = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: fullMessage,
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
      setGuessCardCtx(null);
    }
  }

  async function handleFollowupSend(text) {
    const message = text.trim();
    if (!message || loading) return;

    setDraft("");
    setError("");
    setGuessSentences([]);
    setMessages((prev) => [...prev, { role: "user", content: message }]);

    if (guessCardCtx) {
      // GUESS_CARD 快捷路径：跳过泛方案卡片，直接生成个性化最终方案
      setLoading(true);
      goToStep("result");
      await submitGuessCardPlan(message);
    } else {
      // 普通路径：拉取泛方案卡片（Round 1）
      fetchTemplateCards(message);
    }
  }

  // ---- Free-text send (fallback / existing path) ----

  async function sendMessage(text) {
    const message = text.trim();
    if (!message || loading) return;

    setDraft("");
    setError("");
    setLoading(true);
    goToStep("result"); // skip structured flow
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

      // Open overlay instead of inline
      setReceiptOverlay({
        receipt: receiptData.receipt,
        shareText: receiptData.share_text,
        actions: receiptData.actions,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "小票生成失败");
    } finally {
      setReceiptLoadingIdx(null);
    }
  }

  function handleComposerFocus() {
    if (step === "idle") {
      goToStep("collecting");
    }
  }

  function handleGuessCardPick(card) {
    // GUESS_CARD 入口：预填卡片已知槽位 → 进入结构化槽位收集 → 再进入地点感知小猜问
    const gf = card.guessFlow || {};

    // 预填 context_modifiers
    setSlots((prev) => {
      const merged = [...new Set([...(prev.context_modifiers || []), ...(gf.context_modifiers || [])])];
      return { ...prev, context_modifiers: merged };
    });

    // 存储卡片上下文，供后续小猜问和方案生成使用
    setGuessCardCtx(card);
    // 进入结构化槽位收集（与普通流程一致）
    goToStep("collecting");
    setError("");
  }

  // ---- Render ----

  return (
    <main className="app-shell">
      <section className="phone-frame">
        <StatusBar />
        <Header
          onReset={resetChat}
          onBack={handleBack}
          canGoBack={step !== "idle" && stepHistory.length > 0}
        />
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
              toastVisible={toastVisible}
              toastKey={petToastCount}
            />
          )}

          {!guessCardCtx && (step === "followup" || step === "templates" || step === "result") && (
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

          {loading && (step === "result" || step === "followup") && (
            <LoadingCard slots={slots} accumulatedSlots={accumulatedSlots} guessCardCtx={guessCardCtx} />
          )}
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
      <ReceiptOverlay
        data={receiptOverlay}
        onClose={() => setReceiptOverlay(null)}
      />
    </main>
  );
}
