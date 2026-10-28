package com.dsefa.flir;
import java.util.*;

/** Display processing is independent of radiometric measurement and raw archives. */
public final class Thermal {
    public static final String[] PALETTES={"Iron","White hot","Black hot","Rainbow","Lava","Arctic","Viridis"};
    public static final String[] MODES={"Auto","Detail","Linear auto","Manual","Background relative"};
    public static final class Settings {
        public String palette="Iron",scale="Auto";
        public double low=15,high=35,emissivity=.95,reflected=20,offset=0,tone=0,span=100;
        public double contrast=1.5,minSpan=1.5,detail=35,denoise=30,deadband=.25,hotSpan=3,learningSeconds=120;
        public int rotation=0;
        public boolean mirror=false,smooth=true,average=true,fahrenheit=false;
        public Settings copy(){Settings s=new Settings();s.palette=palette;s.scale=scale;s.low=low;s.high=high;
            s.emissivity=emissivity;s.reflected=reflected;s.offset=offset;s.tone=tone;s.span=span;s.rotation=rotation;s.mirror=mirror;
            s.contrast=contrast;s.minSpan=minSpan;s.detail=detail;s.denoise=denoise;s.deadband=deadband;s.hotSpan=hotSpan;
            s.learningSeconds=learningSeconds;s.smooth=smooth;s.average=average;s.fahrenheit=fahrenheit;return s;}
    }
    public static double temperature(int raw,double emissivity,double reflected,double offset){
        double e=Math.max(.1,Math.min(1,emissivity));
        double reflectedRaw=16528.178/(.012258549*(Math.exp(1427.5/(reflected+273.15))-1))+1307;
        double corrected=(raw*4.-(1-e)*reflectedRaw)/e;
        // Preserve the working Windows raw14-to-temperature model exactly.
        double log=16528.178/(.012258549*(corrected-1307)+1);
        return log>1?1427.5/Math.log(log)-273.15+offset:Double.NaN;
    }
    public static double[] temperatures(int[] raw,Settings s){double[] t=new double[raw.length];
        for(int i=0;i<t.length;i++)t[i]=temperature(raw[i],s.emissivity,s.reflected,s.offset);return t;}
    public static double displayTemperature(double celsius,Settings s){return s.fahrenheit?celsius*1.8+32:celsius;}
    public static String formatTemperature(double celsius,Settings s){return Double.isFinite(celsius)?String.format(Locale.US,"%.1f °%s",displayTemperature(celsius,s),s.fahrenheit?"F":"C"):"—";}
    /** 3x3 finite-only sampling, clipped to the 160x120 sensor edges. */
    public static double sample(double[] t,int index,boolean average){
        if(t==null||index<0||index>=Math.min(19200,t.length))return Double.NaN;
        if(!average)return t[index];
        int x=index%160,y=index/160,count=0;double sum=0;
        for(int yy=Math.max(0,y-1);yy<=Math.min(119,y+1);yy++)for(int xx=Math.max(0,x-1);xx<=Math.min(159,x+1);xx++){
            int i=yy*160+xx;if(i<t.length&&Double.isFinite(t[i])){sum+=t[i];count++;}}
        return count==0?Double.NaN:sum/count;
    }
    /** Stateless compatibility entry point. Keep a Renderer for live range adaptation. */
    public static int[] render(double[] t,Settings s){return new Renderer().render(t,s,0);}

    public static final class Renderer {
        public double low=0,high=1,background=Double.NaN;
        public String description="No frame";
        private double boundLow,boundHigh,bgAge,bgLow,bgHigh;
        private double[] means,variances;
        private String key;
        private long last;
        private boolean initialized;
        public void reset(){initialized=false;means=null;variances=null;key=null;low=0;high=1;background=Double.NaN;description="No frame";bgAge=0;}
        /** timestamp is the source frame timestamp in milliseconds; repeated timestamps do not learn. */
        public int[] render(double[] t,Settings s,long timestamp){
            if(t==null)throw new IllegalArgumentException("Temperatures required");
            String mode=Arrays.asList(MODES).contains(s.scale)?s.scale:"Auto";
            String current=mode+":"+s.minSpan+":"+s.emissivity+":"+s.reflected+":"+s.offset+":"+s.learningSeconds;
            if(initialized&&(timestamp<last||!current.equals(key)||means!=null&&means.length!=t.length))reset();
            double[] sorted=finiteSorted(t);int[] colors=new int[t.length];
            if(sorted.length==0){Arrays.fill(colors,0xff000000);reset();description="No finite temperatures";return colors;}
            double centre=quantile(sorted,.5),dt=initialized?Math.max(0,(timestamp-last)/1000.0):0;
            double[] clean=t.clone();for(int i=0;i<clean.length;i++)if(!Double.isFinite(clean[i]))clean[i]=centre;
            int width=t.length==19200?160:Math.max(1,t.length),height=t.length==19200?120:1;
            double[] image=mode.equals("Manual")?clean:denoise(clean,width,height,s.denoise);
            double lo,hi;
            if(mode.equals("Manual")){
                lo=s.low;hi=s.high;
                if(!Double.isFinite(lo)||!Double.isFinite(hi)||hi<=lo)throw new IllegalArgumentException("Manual maximum must exceed minimum");
            }else{
                lo=quantile(sorted,.001);hi=quantile(sorted,.999);
                double floor=bounded(s.minSpan,.1,1000,1.5);if(hi-lo<floor){lo=centre-floor/2;hi=centre+floor/2;}
                if(s.smooth&&initialized){boolean cut=Math.abs((lo+hi-boundLow-boundHigh)/2)>Math.max(3,1.5*(boundHigh-boundLow));
                    if(!cut){double a=1-Math.exp(-dt/.25);lo=boundLow+a*(lo-boundLow);hi=boundHigh+a*(hi-boundHigh);}}
            }
            boundLow=lo;boundHigh=hi;
            double[] levels=new double[t.length];
            if(mode.equals("Background relative")){
                updateBackground(t,s,dt);double dead=bounded(s.deadband,0,2,.25);
                hi=Math.max(bgHigh+dead+bounded(s.hotSpan,.5,20,3),quantile(sorted,.995)+.10);lo=bgLow;
                for(int i=0;i<levels.length;i++)levels[i]=backgroundLevel(image[i],bgLow,bgHigh,dead,hi)/255.;
                description="Learned background; nonlinear hot tones";
            }else{
                for(int i=0;i<levels.length;i++)levels[i]=(image[i]-lo)/(hi-lo);
                if(mode.equals("Auto")||mode.equals("Detail")){
                    for(int i=0;i<levels.length;i++)levels[i]=clip(levels[i],0,1);
                    double limit=bounded(s.contrast,1,4,1.5);double[] hist=new double[256];
                    for(int i=0;i<levels.length;i++)if(Double.isFinite(t[i]))hist[clamp((int)Math.round(levels[i]*255))]++;
                    double[] lut=cdf(hist,limit),local=mode.equals("Detail")?clahe(levels,width,height,limit):null;
                    double amount=bounded(s.detail,0,100,35)/100;
                    for(int i=0;i<levels.length;i++){double mapped=.4*levels[i]+.6*lookup(lut,levels[i]*255);
                        levels[i]=local==null?mapped:(1-amount)*mapped+amount*local[i];}
                    description=mode.equals("Detail")?"Local CLAHE; nonlinear histogram domain":"Plateau HEQ; nonlinear histogram domain";
                }else description="Linear temperature scale";
            }
            double span=bounded(s.span,25,400,100)/100,shift=bounded(s.tone,-100,100,0)*.006;
            for(int i=0;i<colors.length;i++)colors[i]=Double.isFinite(t[i])?palette(s.palette,clamp((int)Math.round((.5+(levels[i]-.5)/span+shift)*255))):0xff000000;
            low=lo;high=hi;
            if(mode.equals("Manual")||mode.equals("Linear auto")){double mid=(lo+hi)/2,size=hi-lo;low=mid+(-.5-shift)*span*size;high=mid+(.5-shift)*span*size;}
            last=timestamp;key=current;initialized=true;return colors;
        }
        private void updateBackground(double[] t,Settings s,double dt){
            if(means==null){means=t.clone();variances=new double[t.length];bgAge=0;}
            else if(dt>0){
                boolean cut=false;if(bgAge>=4){int total=0,big=0;double[] diffs=new double[(t.length+15)/16];
                    for(int i=0;i<t.length;i+=16)if(Double.isFinite(t[i])&&Double.isFinite(means[i])){double delta=Math.abs(t[i]-means[i]);diffs[total++]=delta;if(delta>=.8)big++;}
                    if(total>0){Arrays.sort(diffs,0,total);cut=diffs[total/2]>=.7&&(double)big/total>=.65;}}
                if(cut){means=t.clone();Arrays.fill(variances,0);bgAge=0;}
                else {dt=Math.min(10,dt);double am=clip(1-Math.exp(-dt/bounded(s.learningSeconds,1,3600,120)),.001,.2),av=clip(1-Math.exp(-dt/15),.003,.35);
                    for(int i=0;i<t.length;i++)if(Double.isFinite(t[i])){if(!Double.isFinite(means[i])){means[i]=t[i];variances[i]=0;}else{
                        double delta=t[i]-means[i];means[i]+=am*delta;variances[i]=(1-av)*(variances[i]+av*delta*delta);}}bgAge+=dt;}
            }
            double[] candidates=new double[(t.length+3)/4];int n=0;
            for(int i=0;i<t.length;i+=4)if(Double.isFinite(means[i])&&(bgAge<4||variances[i]<=.22*.22))candidates[n++]=means[i];
            if(n<Math.min(250,candidates.length)){n=0;for(int i=0;i<t.length;i+=4)if(Double.isFinite(means[i]))candidates[n++]=means[i];}
            if(n==0){background=0;bgLow=-.35;bgHigh=.35;return;}
            candidates=Arrays.copyOf(candidates,n);Arrays.sort(candidates);background=quantile(candidates,.5);
            bgLow=background-Math.max(.35,Math.min(.85,background-quantile(candidates,.1)+.12));
            bgHigh=background+Math.max(.35,Math.min(.85,quantile(candidates,.9)-background+.12));
        }
    }
    private static double backgroundLevel(double t,double lo,double hi,double dead,double hot){
        if(t<=lo)return 10*(1-clip((lo-t)/2,0,1));if(t<=hi)return 10+18*(t-lo)/Math.max(.05,hi-lo);
        if(t<=hi+dead)return 28;return 34+221*Math.pow(clip((t-hi-dead)/Math.max(.1,hot-hi-dead),0,1),.65);
    }
    private static double[] finiteSorted(double[] a){double[] out=new double[a.length];int n=0;for(double v:a)if(Double.isFinite(v))out[n++]=v;out=Arrays.copyOf(out,n);Arrays.sort(out);return out;}
    private static double quantile(double[] a,double p){double index=(a.length-1)*p;int lo=(int)index;return a[lo]+(a[Math.min(lo+1,a.length-1)]-a[lo])*(index-lo);}
    private static double bounded(double v,double lo,double hi,double fallback){return Double.isFinite(v)?clip(v,lo,hi):fallback;}
    private static double clip(double v,double lo,double hi){return Math.max(lo,Math.min(hi,v));}
    private static double[] cdf(double[] hist,double limit){
        double count=0;for(double v:hist)count+=v;double cap=Math.max(1,count/256*limit),excess=0;
        for(int i=0;i<256;i++){excess+=Math.max(0,hist[i]-cap);hist[i]=Math.min(cap,hist[i]);}
        double sum=0;for(int i=0;i<256;i++){double h=hist[i]+excess/256;hist[i]=(sum+.5*h)/Math.max(1,count);sum+=h;}return hist;
    }
    private static double lookup(double[] lut,double index){int a=(int)index;return lut[a]+(lut[Math.min(255,a+1)]-lut[a])*(index-a);}
    private static double[] denoise(double[] a,int w,int h,double strength){
        double amount=bounded(strength,0,100,30)/100;if(amount==0)return a;
        double[] out=new double[a.length];
        for(int y=0;y<h;y++)for(int x=0;x<w;x++){int i=y*w+x;double total=a[i],weights=1;
            for(int dy=-1;dy<=1;dy++)for(int dx=-1;dx<=1;dx++)if(dx!=0||dy!=0){double other=a[Math.max(0,Math.min(h-1,y+dy))*w+Math.max(0,Math.min(w-1,x+dx))];double delta=(other-a[i])/.15;
                double weight=Math.exp(-.5*delta*delta)*(dx!=0&&dy!=0?.5:.75);total+=weight*other;weights+=weight;}
            out[i]=a[i]*(1-amount)+total/weights*amount;}return out;
    }
    private static double[] clahe(double[] image,int w,int h,double limit){
        int nx=Math.min(4,w),ny=Math.min(4,h);double[][][] luts=new double[ny][nx][];
        double[] cx=new double[nx],cy=new double[ny];
        for(int y=0;y<ny;y++){int y0=y*h/ny,y1=(y+1)*h/ny;cy[y]=(y0+y1-1)/2.;
            for(int x=0;x<nx;x++){int x0=x*w/nx,x1=(x+1)*w/nx;cx[x]=(x0+x1-1)/2.;double[] hist=new double[256];
                for(int yy=y0;yy<y1;yy++)for(int xx=x0;xx<x1;xx++)hist[clamp((int)Math.round(image[yy*w+xx]*255))]++;
                luts[y][x]=cdf(hist,limit);}}
        double[] out=new double[image.length];
        for(int y=0;y<h;y++){double py=axis(cy,y);int y0=(int)py,y1=Math.min(ny-1,y0+1);double fy=py-y0;
            for(int x=0;x<w;x++){double px=axis(cx,x);int x0=(int)px,x1=Math.min(nx-1,x0+1);double fx=px-x0;int i=y*w+x,bin=clamp((int)Math.round(image[i]*255));
                double top=luts[y0][x0][bin]*(1-fx)+luts[y0][x1][bin]*fx,bottom=luts[y1][x0][bin]*(1-fx)+luts[y1][x1][bin]*fx;
                out[i]=top*(1-fy)+bottom*fy;}}return out;
    }
    private static double axis(double[] centers,int p){if(p<=centers[0])return 0;for(int i=1;i<centers.length;i++)if(p<centers[i])return i-1+(p-centers[i-1])/(centers[i]-centers[i-1]);return centers.length-1;}
    static int clamp(int n){return Math.max(0,Math.min(255,n));}
    private static final int[][] IRON={{0,0,10},{13,0,118},{72,0,150},{170,28,92},{238,92,18},{255,205,45},{255,255,255}};
    private static final int[][] RAINBOW={{0,0,80},{0,90,255},{0,255,180},{255,255,0},{255,0,0},{255,255,255}};
    private static final int[][] LAVA={{5,0,12},{65,0,35},{155,16,22},{240,70,5},{255,190,30},{255,255,210}};
    private static final int[][] ARCTIC={{0,5,20},{0,30,100},{0,110,170},{40,210,220},{230,255,255}};
    private static final int[][] VIRIDIS={{68,1,84},{59,82,139},{33,145,140},{94,201,98},{253,231,37}};
    static int palette(String name,int value){
        int v=clamp(value);if("White hot".equals(name))return 0xff000000|(v<<16)|(v<<8)|v;
        if("Black hot".equals(name)){v=255-v;return 0xff000000|(v<<16)|(v<<8)|v;}
        int[][] stops="Rainbow".equals(name)?RAINBOW:"Lava".equals(name)?LAVA:"Arctic".equals(name)?ARCTIC:"Viridis".equals(name)?VIRIDIS:IRON;
        double p=v*(stops.length-1)/255.;int a=Math.min(stops.length-2,(int)p);double f=p-a;
        int r=(int)(stops[a][0]*(1-f)+stops[a+1][0]*f),g=(int)(stops[a][1]*(1-f)+stops[a+1][1]*f),b=(int)(stops[a][2]*(1-f)+stops[a+1][2]*f);
        return 0xff000000|(r<<16)|(g<<8)|b;
    }
}
