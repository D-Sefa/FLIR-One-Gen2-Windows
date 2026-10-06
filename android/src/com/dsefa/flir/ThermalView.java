package com.dsefa.flir;

import android.content.Context;
import android.graphics.*;
import android.view.*;
import java.util.*;

public final class ThermalView extends View {
    public final Thermal.Settings settings=new Thermal.Settings();
    private Bitmap bitmap;private final Paint paint=new Paint(3);
    private final Matrix transform=new Matrix();
    private int[] raw;private double[] temps;
    private long timestamp;private int cursor=-1;
    private final List<Integer> points=new ArrayList<>();
    public interface PointListener{void changed(List<Integer> points);}
    public PointListener listener;
    public ThermalView(Context c){super(c);setBackgroundColor(Color.rgb(5,6,9));}
    public void frame(int[] r,long t){raw=r;timestamp=t;refresh();}
    public int[] raw(){return raw;}
    public double[] temperatures(){return temps;}
    public List<Integer> points(){return new ArrayList<>(points);}
    public void clearPoints(){points.clear();if(listener!=null)listener.changed(points());invalidate();}
    public void refresh(){if(raw==null)return;temps=Thermal.temperatures(raw,settings);
        int[] pixels=Thermal.render(temps,settings);
        if(bitmap==null)bitmap=Bitmap.createBitmap(160,120,Bitmap.Config.ARGB_8888);
        bitmap.setPixels(pixels,0,160,0,0,160,120);invalidate();}
    public double sample(int i){if(temps==null||i<0||i>=temps.length)return Double.NaN;
        int x=i%160,y=i/160;double sum=0;int count=0;
        for(int yy=Math.max(0,y-1);yy<=Math.min(119,y+1);yy++)for(int xx=Math.max(0,x-1);xx<=Math.min(159,x+1);xx++){
            double v=temps[yy*160+xx];if(Double.isFinite(v)){sum+=v;count++;}}
        return count>0?sum/count:Double.NaN;
    }
    private float density(){return getResources().getDisplayMetrics().density;}
    private void matrix(){
        boolean sideways=settings.rotation%180!=0;
        float availableH=Math.max(1,getHeight()-58*density());
        float scale=Math.min(getWidth()/(sideways?120f:160f),availableH/(sideways?160f:120f));
        transform.reset();transform.postTranslate(-80,-60);
        transform.postScale(settings.mirror?-1:1,1);transform.postRotate(settings.rotation);
        transform.postScale(scale,scale);transform.postTranslate(getWidth()/2f,availableH/2f);
    }
    protected void onDraw(Canvas canvas){super.onDraw(canvas);paint.setColor(0xffb5bbc4);paint.setTextSize(14*density());
        if(bitmap==null){canvas.drawText("Connect FLIR ONE Gen 2 through USB OTG",12*density(),getHeight()/2f,paint);return;}
        matrix();paint.setFilterBitmap(true);canvas.drawBitmap(bitmap,transform,paint);
        for(int n=0;n<points.size();n++)marker(canvas,points.get(n),"P"+(n+1)+" "+String.format(Locale.US,"%.1f°C",sample(points.get(n))),0xffffd45c);
        if(cursor>=0)marker(canvas,cursor,String.format(Locale.US,"%.1f°C",sample(cursor)),0xffffffff);
        double min=Double.POSITIVE_INFINITY,max=Double.NEGATIVE_INFINITY;
        for(double v:temps)if(Double.isFinite(v)){min=Math.min(min,v);max=Math.max(max,v);}
        paint.setColor(0xffe6e9ef);paint.setTextSize(13*density());
        canvas.drawText(String.format(Locale.US,"Min %.1f°C   Center %.1f°C   Max %.1f°C",min,sample(60*160+80),max),8*density(),getHeight()-33*density(),paint);
        paint.setColor(0xff9ca7b7);paint.setTextSize(11*density());
        canvas.drawText("Tap: measure / pin · Tap near pin: remove",8*density(),getHeight()-12*density(),paint);
    }
    private void marker(Canvas c,int i,String label,int color){float[] p={i%160+.5f,i/160+.5f};transform.mapPoints(p);
        paint.setColor(color);paint.setStrokeWidth(density());c.drawLine(p[0]-7,p[1],p[0]+7,p[1],paint);c.drawLine(p[0],p[1]-7,p[0],p[1]+7,paint);
        paint.setTextSize(12*density());c.drawText(label,Math.min(p[0]+8,getWidth()-100*density()),Math.max(14*density(),p[1]-8),paint);}
    public boolean onTouchEvent(MotionEvent event){if(bitmap==null)return true;
        float[] p={event.getX(),event.getY()};Matrix inverse=new Matrix();matrix();if(!transform.invert(inverse))return true;inverse.mapPoints(p);
        if(p[0]<0||p[0]>=160||p[1]<0||p[1]>=120)return true;
        cursor=(int)p[1]*160+(int)p[0];
        if(event.getAction()==MotionEvent.ACTION_UP){int near=-1;
            for(int i=0;i<points.size();i++)if(Math.hypot(points.get(i)%160-p[0],points.get(i)/160-p[1])<5){near=i;break;}
            if(near>=0)points.remove(near);else if(points.size()<8)points.add(cursor);
            if(listener!=null)listener.changed(points());performClick();}
        invalidate();return true;}
    public boolean performClick(){super.performClick();return true;}
    public Bitmap snapshot(){Bitmap b=Bitmap.createBitmap(Math.max(1,getWidth()),Math.max(1,getHeight()),Bitmap.Config.ARGB_8888);draw(new Canvas(b));return b;}
}
