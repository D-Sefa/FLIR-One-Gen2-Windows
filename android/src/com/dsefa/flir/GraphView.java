package com.dsefa.flir;

import android.content.Context;
import android.graphics.*;
import android.view.*;
import java.util.*;
import java.text.SimpleDateFormat;

public final class GraphView extends View {
    private final GraphModel model=new GraphModel();private final Paint p=new Paint(3);
    private long hover;private float downX,lastX;private boolean dragging;
    private final ScaleGestureDetector pinch;public Thermal.Settings settings;
    public GraphView(Context c){super(c);setBackgroundColor(0xff0d141e);pinch=new ScaleGestureDetector(c,new ScaleGestureDetector.SimpleOnScaleGestureListener(){public boolean onScale(ScaleGestureDetector d){zoom(1/d.getScaleFactor());return true;}});}
    public void add(long stamp,double[] values){model.add(stamp,values);invalidate();}
    public void clear(){model.clear();hover=0;invalidate();}
    public void pause(boolean value){model.pause(value);invalidate();}
    public boolean paused(){return model.paused();}
    public void live(){model.live();hover=0;invalidate();}
    public void zoom(double factor){model.zoom(factor);invalidate();}
    private double unit(double v){return settings!=null?Thermal.displayTemperature(v,settings):v;}
    protected void onDraw(Canvas canvas){super.onDraw(canvas);float d=getResources().getDisplayMetrics().density;
        float left=43*d,right=getWidth()-12*d,top=57*d,bottom=getHeight()-26*d;if(right<=left||bottom<=top)return;
        long end=model.end(),window=model.window();boolean paused=model.paused();List<GraphModel.Sample> samples=model.samples();
        p.setTextSize(10*d);double low=Double.POSITIVE_INFINITY,high=Double.NEGATIVE_INFINITY;
        for(GraphModel.Sample s:samples)if(s.stamp>=end-window&&s.stamp<=end)for(double v:s.values)if(Double.isFinite(v)){low=Math.min(low,unit(v));high=Math.max(high,unit(v));}
        if(!Double.isFinite(low)){p.setColor(0xffa4adbc);canvas.drawText("Live maximum + pinned measurements",12*d,30*d,p);return;}
        double span=Math.max(.5,high-low);low-=span*.1;high=low+span*1.2;
        p.setColor(0xff303742);p.setStrokeWidth(1);
        for(int i=0;i<=3;i++){float y=top+(bottom-top)*i/3;canvas.drawLine(left,y,right,y,p);
            p.setColor(0xffa4adbc);canvas.drawText(String.format(Locale.US,"%.1f",high-(high-low)*i/3),3*d,y+4*d,p);p.setColor(0xff303742);}
        int[] colors={0xffe7eff6,0xffffd45c,0xff64b5ff,0xffff8e91,0xff82db9c,0xffbb93ef,0xffffae63,0xffdddddd,0xff53d6d1};
        for(int n=0;n<9;n++){Path path=new Path();boolean begun=false;long previous=0;
            for(GraphModel.Sample s:samples){if(s.stamp<end-window||s.stamp>end||n>=s.values.length||!Double.isFinite(s.values[n])){begun=false;continue;}
                float x=left+(right-left)*(s.stamp-(end-window))/(float)window;
                float y=bottom-(float)((unit(s.values[n])-low)/(high-low))*(bottom-top);
                if(!begun||s.stamp-previous>2500){path.moveTo(x,y);begun=true;}else path.lineTo(x,y);previous=s.stamp;}
            p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(1.5f*d);p.setColor(colors[n]);canvas.drawPath(path,p);p.setStyle(Paint.Style.FILL);}
        p.setColor(0xffa4adbc);canvas.drawText((window/1000)+"s history"+(paused?" · graph paused (measurement continues)":" · live"),left,getHeight()-7*d,p);
        if(hover>0){GraphModel.Sample nearest=model.nearest(hover);
            if(nearest!=null&&nearest.stamp>=end-window&&nearest.stamp<=end){float x=left+(right-left)*(nearest.stamp-(end-window))/(float)window;
                p.setPathEffect(new DashPathEffect(new float[]{4*d,4*d},0));canvas.drawLine(x,top,x,bottom,p);p.setPathEffect(null);
                long age=Math.max(0,(System.currentTimeMillis()-nearest.stamp)/1000);
                String time=new SimpleDateFormat("yyyy-MM-dd HH:mm:ss",Locale.US).format(new Date(nearest.stamp));
                StringBuilder temp=new StringBuilder();for(int i=0;i<nearest.values.length;i++){if(i>0)temp.append(" · ");temp.append(i==0?"MAX":"P"+i).append(String.format(Locale.US," %.1f°",unit(nearest.values[i])));}
                p.setColor(0xffeeeeee);canvas.save();canvas.clipRect(0,0,getWidth(),top);canvas.drawText(temp.toString(),12*d,18*d,p);
                p.setTextSize(9*d);canvas.drawText(time+" · "+GraphModel.age(age*1000),12*d,36*d,p);canvas.restore();
            }}
    }
    public boolean onTouchEvent(MotionEvent e){getParent().requestDisallowInterceptTouchEvent(true);pinch.onTouchEvent(e);float d=getResources().getDisplayMetrics().density;
        if(e.getActionMasked()==MotionEvent.ACTION_DOWN){downX=lastX=e.getX();dragging=false;}
        if(e.getActionMasked()==MotionEvent.ACTION_MOVE&&!pinch.isInProgress()&&e.getPointerCount()==1){if(Math.abs(e.getX()-downX)>12*d)dragging=true;
            if(dragging)model.pan((lastX-e.getX())/Math.max(1,getWidth()-55*d));lastX=e.getX();}
        hover=model.end()-model.window()+(long)(Math.max(0,Math.min(1,(e.getX()-43*d)/Math.max(1,getWidth()-55*d)))*model.window());
        if(e.getActionMasked()==MotionEvent.ACTION_UP||e.getActionMasked()==MotionEvent.ACTION_CANCEL){getParent().requestDisallowInterceptTouchEvent(false);performClick();}
        invalidate();return true;}
    public boolean performClick(){super.performClick();return true;}
}
