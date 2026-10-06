package com.dsefa.flir;

import android.content.Context;
import android.graphics.*;
import android.view.*;
import java.util.*;
import java.text.SimpleDateFormat;

public final class GraphView extends View {
    private static final class Sample{long stamp;double[] values;}
    private final Deque<Sample> samples=new ArrayDeque<>();private final Paint p=new Paint(3);
    private long window=30000,end,hover;private boolean paused;
    public GraphView(Context c){super(c);setBackgroundColor(0xff0d1016);}
    public void add(long stamp,double[] values){Sample s=new Sample();s.stamp=stamp;s.values=values;samples.addLast(s);
        while(samples.size()>30000)samples.removeFirst();if(!paused)end=stamp;invalidate();}
    public void clear(){samples.clear();hover=0;invalidate();}
    public void pause(boolean value){paused=value;if(!value&&!samples.isEmpty())end=samples.getLast().stamp;invalidate();}
    public void zoom(double factor){window=(long)Math.max(5000,Math.min(3600000,window*factor));invalidate();}
    protected void onDraw(Canvas canvas){super.onDraw(canvas);float d=getResources().getDisplayMetrics().density;
        float left=46*d,right=getWidth()-8*d,top=22*d,bottom=getHeight()-25*d;
        p.setTextSize(10*d);double low=Double.POSITIVE_INFINITY,high=Double.NEGATIVE_INFINITY;
        for(Sample s:samples)if(s.stamp>=end-window&&s.stamp<=end)for(double v:s.values)if(Double.isFinite(v)){low=Math.min(low,v);high=Math.max(high,v);}
        if(!Double.isFinite(low)){p.setColor(0xffa4adbc);canvas.drawText("Pin a measurement point to plot its temperature",12*d,40*d,p);return;}
        double span=Math.max(.5,high-low);low-=span*.1;high=low+span*1.2;
        p.setColor(0xff303742);p.setStrokeWidth(1);
        for(int i=0;i<=3;i++){float y=top+(bottom-top)*i/3;canvas.drawLine(left,y,right,y,p);
            p.setColor(0xffa4adbc);canvas.drawText(String.format(Locale.US,"%.1f",high-(high-low)*i/3),3*d,y+4*d,p);p.setColor(0xff303742);}
        int[] colors={0xffffd45c,0xff64b5ff,0xffff8e91,0xff82db9c,0xffbb93ef,0xffffae63,0xffdddddd,0xff53d6d1};
        for(int n=0;n<8;n++){Path path=new Path();boolean begun=false;
            for(Sample s:samples){if(s.stamp<end-window||s.stamp>end||n>=s.values.length||!Double.isFinite(s.values[n]))continue;
                float x=left+(right-left)*(s.stamp-(end-window))/(float)window;
                float y=bottom-(float)((s.values[n]-low)/(high-low))*(bottom-top);
                if(!begun){path.moveTo(x,y);begun=true;}else path.lineTo(x,y);}
            p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(1.5f*d);p.setColor(colors[n]);canvas.drawPath(path,p);p.setStyle(Paint.Style.FILL);}
        p.setColor(0xffa4adbc);canvas.drawText((window/1000)+"s history"+(paused?" · graph paused (measurement continues)":" · live"),left,getHeight()-7*d,p);
        if(hover>0){Sample nearest=null;for(Sample s:samples)if(s.stamp>=end-window&&s.stamp<=end&&(nearest==null||Math.abs(s.stamp-hover)<Math.abs(nearest.stamp-hover)))nearest=s;
            if(nearest!=null){float x=left+(right-left)*(nearest.stamp-(end-window))/(float)window;
                p.setPathEffect(new DashPathEffect(new float[]{4*d,4*d},0));canvas.drawLine(x,top,x,bottom,p);p.setPathEffect(null);
                long age=Math.max(0,(System.currentTimeMillis()-nearest.stamp)/1000);
                String time=new SimpleDateFormat("yyyy-MM-dd HH:mm:ss",Locale.US).format(new Date(nearest.stamp));
                String temp=nearest.values.length>0?String.format(Locale.US,"P1 %.1f°C",nearest.values[0]):"";
                p.setColor(0xffeeeeee);canvas.drawText(temp+" · "+time+" · "+age/3600+"h "+age%3600/60+"m "+age%60+"s ago",left,14*d,p);
            }}
    }
    public boolean onTouchEvent(MotionEvent e){float d=getResources().getDisplayMetrics().density;
        hover=end-window+(long)(Math.max(0,Math.min(1,(e.getX()-46*d)/Math.max(1,getWidth()-54*d)))*window);invalidate();return true;}
}
