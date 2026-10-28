package com.dsefa.flir;

import java.util.*;

/** Small bounded maximum-temperature timeline; no display or USB dependencies. */
public final class OverlayModel {
    public static final long WINDOW=30000;
    public static final class Sample {
        public final long stamp;public final double value;
        Sample(long stamp,double value){this.stamp=stamp;this.value=value;}
    }
    private final Deque<Sample> history=new ArrayDeque<>();
    public void add(long stamp,double[] temperatures){
        double max=Double.NEGATIVE_INFINITY;
        for(double v:temperatures)if(Double.isFinite(v))max=Math.max(max,v);
        if(!Double.isFinite(max))return;
        if(!history.isEmpty()&&stamp<history.getLast().stamp)clear();
        history.addLast(new Sample(stamp,max));
        while(!history.isEmpty()&&(history.getFirst().stamp<stamp-WINDOW||history.size()>600))history.removeFirst();
    }
    public List<Sample> samples(){return new ArrayList<>(history);}
    public void clear(){history.clear();}
    public static String line(int index,double temperature){return String.format(Locale.US,"P%d  ·  %.1f °C",index+1,temperature);}
    public static int textColor(int[] pixels){
        // sRGB relative luminance: choose the color with the higher contrast.
        double luminance=0;
        for(int c:pixels)luminance+=.2126*linear((c>>16)&255)+.7152*linear((c>>8)&255)+.0722*linear(c&255);
        return pixels.length>0&&luminance/pixels.length>.179?0xff000000:0xffffffff;
    }
    private static double linear(int channel){double s=channel/255.;return s<=.04045?s/12.92:Math.pow((s+.055)/1.055,2.4);}
}
