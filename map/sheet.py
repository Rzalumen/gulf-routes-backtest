import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import icons, app
W,H=1280,900
fig=plt.figure(figsize=(W/100,H/100),dpi=100); fig.patch.set_facecolor('#161c22')
ax=fig.add_axes([0,0,1,1]); ax.set_xlim(0,W); ax.set_ylim(0,H); ax.axis('off')
ax.add_patch(matplotlib.patches.Rectangle((0,H-58),W,58,color='#0f1317'))
ax.text(20,H-29,'gulf situation',color='#7d8893',fontsize=11,va='center')
ax.text(130,H-29,'TANKER',color='#9dbb6b',fontsize=21,fontweight='bold',va='center')
ax.text(W-20,H-29,'new title bar: channel name small, category big',color='#7d8893',fontsize=10,va='center',ha='right')
ax.text(20,H-90,'ICONS  (own drawings · size follows the real aircraft · colour = altitude on the map)',color='#cfd6dd',fontsize=12,fontweight='bold')
demo=[('heavy4',42,'C-5M'),('heavy4',40,'B-52'),('heavy4',36,'KC-135 / C-17 / E-3'),('heavy4',34,'RC-135'),('twin',34,'KC-46 / Voyager'),
      ('twin',30,'P-8 / C-32 / C-40'),('turboprop',30,'C-130 / A400M'),('bomber',32,'B-1B'),('flyingwing',36,'B-2'),('drone',30,'RQ-4 / MQ-4C'),
      ('fighter',20,'F-15/16/22/35'),('tiltrotor',22,'CV-22'),('helicopter',22,'CH-47'),('drone',18,'MQ-9'),('twin',20,'C-37 / Gulfstream'),('turboprop',16,'C-12 (Army)')]
for i,(shape,size,lab) in enumerate(demo):
    x=90+(i%8)*150; y=H-200-(i//8)*150
    for p,al in icons.markers(shape,0):
        ax.plot(x,y,marker=p,markersize=size*2.2,color=app.alt_color(30000),markeredgecolor='#000',markeredgewidth=0.8,alpha=al,linestyle='none')
    ax.text(x,y-62,lab,color='#cfd6dd',fontsize=9.5,ha='center')
ax.text(20,H-520,'CATEGORY TAGS  (left panel)',color='#cfd6dd',fontsize=12,fontweight='bold')
for i,(c,col) in enumerate(icons.CAT_COLOR.items()):
    x=24+(i%4)*310; y=H-570-(i//4)*48
    ax.text(x,y,c,color='#111418',fontsize=11,fontweight='bold',va='center',bbox=dict(boxstyle='round,pad=0.35',facecolor=col,edgecolor='none'))
ax.text(20,24,'SAMPLE SHEET · icons drawn for Gulf Situation (not copied from ADS-B Exchange / Flightradar24)',color='#7d8893',fontsize=10)
fig.savefig('/home/claude/mapsvc/icon_sheet.jpg',dpi=100,facecolor='#161c22',pil_kwargs={'quality':90})
