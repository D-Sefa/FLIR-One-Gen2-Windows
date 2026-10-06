package com.dsefa.flir;
import java.util.*;

public final class Thermal {
    public static final class Settings {
        public String palette="Iron",scale="Auto";
        public double low=15,high=35,emissivity=.95,reflected=20,offset=0,tone=0,span=100;
        public int rotation=0;public boolean mirror=false;
        public Settings copy(){Settings s=new Settings();s.palette=palette;s.scale=scale;s.low=low;s.high=high;
            s.emissivity=emissivity;s.reflected=reflected;s.offset=offset;s.tone=tone;s.span=span;s.rotation=rotation;s.mirror=mirror;return s;}
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
    public static int[] render(double[] t,Settings s){
        double[] sorted=Arrays.stream(t).filter(Double::isFinite).sorted().toArray();
        int[] colors=new int[t.length];if(sorted.length==0)return colors;
        double lo=s.low,hi=s.high;
        if(!s.scale.equals("Manual")){lo=sorted[(int)((sorted.length-1)*.001)];hi=sorted[(int)((sorted.length-1)*.999)];
            if(hi-lo<1.5){double centre=sorted[sorted.length/2];lo=centre-.75;hi=centre+.75;}}
        double range=Math.max(.1,hi-lo);double[] cdf=new double[256];
        if(s.scale.equals("Auto")){
            double[] hist=new double[256];for(double v:t)if(Double.isFinite(v))hist[clamp((int)Math.round((v-lo)*255/range))]++;
            double cap=Math.max(1,sorted.length/256.*1.5),excess=0;
            for(int i=0;i<256;i++){excess+=Math.max(0,hist[i]-cap);hist[i]=Math.min(cap,hist[i]);}
            double cumulative=0;for(int i=0;i<256;i++){hist[i]+=excess/256;cdf[i]=(cumulative+.5*hist[i])/sorted.length;cumulative+=hist[i];}
        }
        for(int i=0;i<t.length;i++){
            double linear=Math.max(0,Math.min(1,(t[i]-lo)/range));
            double level=s.scale.equals("Auto")?.4*linear+.6*cdf[clamp((int)Math.round(linear*255))]:linear;
            level=.5+(level-.5)/Math.max(.25,s.span/100.)+s.tone*.006;
            colors[i]=Double.isFinite(t[i])?palette(s.palette,clamp((int)Math.round(level*255))):0xff000000;
        }return colors;
    }
    static int clamp(int n){return Math.max(0,Math.min(255,n));}
    static int palette(String name,int v){
        if(name.equals("White hot"))return 0xff000000|(v<<16)|(v<<8)|v;
        if(name.equals("Black hot")){v=255-v;return 0xff000000|(v<<16)|(v<<8)|v;}
        int[][] stops=name.equals("Rainbow")?new int[][]{{0,0,80},{0,90,255},{0,255,180},{255,255,0},{255,0,0},{255,255,255}}:
            new int[][]{{0,0,10},{13,0,118},{72,0,150},{170,28,92},{238,92,18},{255,205,45},{255,255,255}};
        double p=v*(stops.length-1)/255.;int a=Math.min(stops.length-2,(int)p);double f=p-a;
        int r=(int)(stops[a][0]*(1-f)+stops[a+1][0]*f),g=(int)(stops[a][1]*(1-f)+stops[a+1][1]*f),b=(int)(stops[a][2]*(1-f)+stops[a+1][2]*f);
        return 0xff000000|(r<<16)|(g<<8)|b;
    }
}
